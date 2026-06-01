"""
Hybrid RAG — استرجاع هجين (LegalArticle/PostgreSQL + Pinecone)

المشاكل المُصلحة في هذا الإصدار:
  1. البحث برقم المادة: يستخدم LegalArticle ORM مباشرةً بدلاً من
     الاعتماد الكلي على Pinecone $in filter الذي يفشل مع بعض الأرقام.
  2. المواد المفقودة (163 مادة): تحسين المحلل ليغطي:
     - الأرقام العربية (٢٣٣) بدون تحويل
     - أشكال PyPDF2 المكسورة: "الم ادة", "الماد ة", "الم اد ة"
     - المواد ذات الحروف: "مادة أ", "مادة ب"
     - المواد في منتصف السطر (search بدل match)
     - تخزين num_int مع كل مادة للـ LegalArticle
"""

from __future__ import annotations

import re
import time
import hashlib
import logging
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Dict, Optional
from pathlib import Path

import PyPDF2
from openai import OpenAI
from pinecone import Pinecone
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

# ── تهيئة العملاء ──
client = OpenAI(api_key=settings.OPENAI_API_KEY)
pc     = Pinecone(api_key=settings.PINECONE_API_KEY)
index  = pc.Index(settings.PINECONE_INDEX_NAME)

# ── الثوابت ──
MAX_SECTION_SIZE = 4000
GROUP_SIZE       = 3
GROUP_OVERLAP    = 1
MIN_CHUNK_SIZE   = 60
BATCH_SIZE       = getattr(settings, 'RAG_BATCH_SIZE', 50)
TOP_K            = getattr(settings, 'RAG_TOP_K_RESULTS', 5)
RRF_K            = 60
PG_WEIGHT        = 0.45
VEC_WEIGHT       = 0.55

# ──────────────────────────────────────────────────────────────
# نمط التعرف على المواد — مُوسَّع ليشمل كل أشكال الكتابة
# يتعرف على:
#   "المادة 233"  "مادة 233"  "المادة رقم 233"
#   "المادة ٢٣٣"  (أرقام عربية)
#   "الم ادة 233" "الماد ة"  "الم اد ة"  (كسور PyPDF2)
#   "مادة الأولى" "مادة أ"   (حروف وأسماء)
# ──────────────────────────────────────────────────────────────
ARTICLE_RE = re.compile(
    r'(?:'
    r'ال(?:م\s*ا\s*د\s*ة|م\s*ادة|مادة)'   # المادة بأشكالها
    r'|(?<!\w)مادة'                          # مادة منفردة
    r')'
    r'\s*(?:رقم\s*)?'
    r'(?:[٠-٩\d]+(?:/[٠-٩\d]+)?'
    r'|الأول[ىي]?|الثاني[ةه]?|الثالث[ةه]?|الرابع[ةه]?|الخامس[ةه]?'
    r'|السادس[ةه]?|السابع[ةه]?|الثامن[ةه]?|التاسع[ةه]?|العاشر[ةه]?'
    r'|[أ-ي](?:\s*[-]\s*[أ-ي])?'
    r')',
    re.UNICODE,
)

_NUM_RE = re.compile(r'([٠-٩\d]+)', re.UNICODE)
_AR2LA  = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s.translate(_AR2LA))
    except Exception:
        return None


def _extract_num(label: str) -> Optional[int]:
    """يستخرج أول رقم من label المادة."""
    m = _NUM_RE.search(label)
    return _to_int(m.group(1)) if m else None


# =============================================================================
#  §1  Router
# =============================================================================

class QueryIntent(str, Enum):
    ARTICLE_EXACT = "article_exact"
    ARTICLE_RANGE = "article_range"
    TOPIC         = "topic"
    KEYWORD       = "keyword"
    GENERAL       = "general"


@dataclass
class RouterResult:
    intent:    QueryIntent
    art_nums:  list[int]    = field(default_factory=list)
    art_range: tuple | None = None
    keywords:  list[str]   = field(default_factory=list)
    topic:     str          = ""
    routed_by: str          = "regex"
    doc_ids:   list[int]    = field(default_factory=list)   # وثائق محددة (اختياري)


_EXACT_RE = re.compile(
    r'(?:المادة|مادة)\s*(?:رقم\s*)?([٠-٩\d]+(?:\s*[،,]\s*[٠-٩\d]+)*)',
    re.UNICODE,
)
_RANGE_RE = re.compile(
    r'(?:المواد|مواد)\s*(?:من\s*)?([٠-٩\d]+)\s*(?:إلى|حتى|-|–)\s*([٠-٩\d]+)',
    re.UNICODE,
)
_LEGAL_KW = {
    'الطلاق','الزواج','النفقة','الحضانة','الإرث','الميراث','الوصية',
    'العقد','التعويض','المسؤولية','العقوبة','الجريمة','الشركة','الملكية',
    'الإيجار','البيع','الشراء','الوكالة','التقادم','الدعوى','الاستئناف',
    'التمييز','الحكم','القرار','الأهلية','الولاية','الوصاية','الكفالة',
    'الرهن','الدين','القرض','الفائدة','الغرامة','السجن','الاحتجاز',
}


def _detect_doc_ids(query: str) -> list[int]:
    """يكتشف أسماء الوثائق المذكورة في السؤال ويعيد doc_ids المطابقة."""
    try:
        from .models import Document
        docs = list(Document.objects.filter(is_indexed=True).values('id', 'title'))
        matched = []
        for d in docs:
            title = (d['title'] or '').strip()
            if len(title) >= 4 and title in query:
                matched.append(d['id'])
        return matched
    except Exception:
        return []


def route_query(query: str) -> RouterResult:
    q = query.strip()
    n = q.translate(_AR2LA)   # حوّل الأرقام العربية

    # اكتشاف اسم القانون من السؤال (يُستخدم لتضييق البحث لوثيقة محددة)
    doc_ids = _detect_doc_ids(q)

    m = _RANGE_RE.search(n)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi: lo, hi = hi, lo
        return RouterResult(QueryIntent.ARTICLE_RANGE,
                            art_nums=list(range(lo, hi+1)),
                            art_range=(lo, hi), routed_by="regex",
                            doc_ids=doc_ids)

    m = _EXACT_RE.search(n)
    if m:
        nums = [int(x) for x in re.findall(r'\d+', m.group(1))]
        return RouterResult(QueryIntent.ARTICLE_EXACT, art_nums=nums,
                            routed_by="regex", doc_ids=doc_ids)

    topic_re = re.compile(
        r'(?:ما\s+هو|ما\s+هي|اشرح|عرّف|تعريف|معنى|أحكام|شروط|إجراءات)\s+(.+)',
        re.UNICODE)
    m2 = topic_re.search(q)
    if m2:
        topic = m2.group(1).strip()
        kw = [w for w in topic.split() if w in _LEGAL_KW]
        return RouterResult(QueryIntent.TOPIC, keywords=kw, topic=topic,
                            routed_by="regex", doc_ids=doc_ids)

    found = [w for w in _LEGAL_KW if w in q]
    if found:
        return RouterResult(QueryIntent.KEYWORD, keywords=found, topic=q,
                            routed_by="regex", doc_ids=doc_ids)

    return RouterResult(QueryIntent.GENERAL, routed_by="regex", doc_ids=doc_ids)


# =============================================================================
#  §2  Structured Search — LegalArticle ORM
# =============================================================================

def structured_search(query: str, router: RouterResult, top_k: int = 10) -> list[dict]:
    """
    يبحث في LegalArticle مباشرةً بالرقم — دقيق 100%.
    WHERE article_number IN (233)   بدلاً من Pinecone $in filter.
    """
    from .models import LegalArticle

    qs = LegalArticle.objects.select_related('doc').order_by('order_in_doc')

    # تضييق البحث لوثيقة محددة إذا ذُكر اسم القانون في السؤال
    if router.doc_ids:
        qs = qs.filter(doc_id__in=router.doc_ids)
        logger.info(f"[Structured] تصفية بالوثيقة doc_ids={router.doc_ids}")

    if router.intent == QueryIntent.ARTICLE_EXACT and router.art_nums:
        arts = list(qs.filter(article_number__in=router.art_nums)[:top_k * 3])
        logger.info(f"[Structured/EXACT] {len(arts)} مادة للأرقام {router.art_nums}")

    elif router.intent == QueryIntent.ARTICLE_RANGE and router.art_range:
        lo, hi = router.art_range
        arts = list(qs.filter(article_number__gte=lo, article_number__lte=hi)[:top_k * 3])
        logger.info(f"[Structured/RANGE] {len(arts)} مادة [{lo}-{hi}]")

    elif router.intent in (QueryIntent.KEYWORD, QueryIntent.TOPIC):
        from django.db.models import Q
        terms = (router.keywords or [router.topic or query])[:4]
        qf = Q()
        for t in terms:
            if t: qf |= Q(text__icontains=t) | Q(section_path__icontains=t)
        arts = list(qs.filter(qf)[:top_k * 2])
        logger.info(f"[Structured/KW] {len(arts)} مادة للكلمات {terms}")

    else:
        arts = []

    chunks = []
    for rank, a in enumerate(arts, 1):
        c = a.to_rag_chunk()
        c['pg_rank'] = 1.0 / rank
        chunks.append(c)
    return chunks


# =============================================================================
#  §3  Semantic Search — Pinecone
# =============================================================================

def semantic_search(query: str, router: RouterResult, top_k: int = 10) -> list[dict]:
    try:
        qvec = embed_text(query)
    except Exception as e:
        logger.error(f"[Semantic] embed failed: {e}")
        return []

    seen: set[str] = set()
    matches: list  = []

    # فلتر قاعدي: تضييق Pinecone لوثائق محددة إذا ذُكر اسم القانون في السؤال
    _doc_flt = (
        {"doc_id": {"$in": [str(d) for d in router.doc_ids]}}
        if router.doc_ids else None
    )

    def _merge_flt(*flts):
        """يدمج فلترَين أو أكثر بـ $and إذا لزم."""
        active = [f for f in flts if f]
        if not active:       return None
        if len(active) == 1: return active[0]
        return {"$and": active}

    def _q(flt=None, mult=4):
        try:
            kw = dict(vector=qvec, top_k=top_k * mult, include_metadata=True)
            combined = _merge_flt(_doc_flt, flt)
            if combined: kw["filter"] = combined
            return index.query(**kw).get("matches", [])
        except Exception as e:
            logger.error(f"[Pinecone] {e}")
            return []

    def _collect(ms):
        for m in ms:
            mid = m.get("id", "")
            if mid and mid not in seen:
                seen.add(mid); matches.append(m)

    if router.intent in (QueryIntent.ARTICLE_EXACT, QueryIntent.ARTICLE_RANGE):
        str_nums = [str(n) for n in router.art_nums]
        if str_nums:
            _collect(_q({"art_nums": {"$in": str_nums}}, 5))
        if len(matches) < top_k:
            _collect(_q(mult=4))
    elif router.intent == QueryIntent.TOPIC:
        _collect(_q(mult=6))
    elif router.intent == QueryIntent.KEYWORD:
        _collect(_q(mult=4))
        for kw in router.keywords[:2]:
            try:
                r2 = index.query(
                    vector=embed_text(kw), top_k=top_k, include_metadata=True,
                    **({"filter": _doc_flt} if _doc_flt else {}),
                )
                _collect(r2.get("matches", []))
            except Exception:
                pass
    else:
        _collect(_q(mult=4))
    if _doc_flt:
        logger.info(f"[Semantic] Pinecone فلتر وثيقة doc_ids={router.doc_ids}")

    min_score = 0.10 if router.intent in (
        QueryIntent.ARTICLE_EXACT, QueryIntent.ARTICLE_RANGE
    ) else 0.15

    results = []
    for m in matches:
        meta  = m.get("metadata", {})
        score = round(m.get("score", 0), 4)
        if score < min_score: continue
        results.append({
            "text":      meta.get("text", ""),
            "doc_title": meta.get("doc_title", "وثيقة"),
            "header":    meta.get("header", ""),
            "articles":  meta.get("articles", ""),
            "art_nums":  meta.get("art_nums", []),
            "type":      meta.get("type", "paragraph"),
            "vec_score": score,
            "source":    "pinecone",
        })

    logger.info(f"[Semantic] {len(results)} نتيجة")
    return results


# =============================================================================
#  §4  Fusion: RRF + تنويع
# =============================================================================

def _rrf_fuse(pg: list[dict], vec: list[dict], top_k: int) -> list[dict]:
    scores: dict[str, float] = {}
    cmap:   dict[str, dict]  = {}

    def key(c): return c.get("text", "")[:120].strip()

    for rank, c in enumerate(pg, 1):
        k = key(c)
        if not k: continue
        scores[k] = scores.get(k, 0) + PG_WEIGHT / (RRF_K + rank)
        if k not in cmap: cmap[k] = c

    for rank, c in enumerate(vec, 1):
        k = key(c)
        if not k: continue
        scores[k] = scores.get(k, 0) + VEC_WEIGHT / (RRF_K + rank)
        if k not in cmap:
            cmap[k] = {**c}
        else:
            cmap[k]["vec_score"] = c.get("vec_score", 0)
            cmap[k]["source"]    = "hybrid"

    fused = []
    for k in sorted(scores, key=lambda x: scores[x], reverse=True):
        c = cmap[k].copy()
        c["score"] = round(scores[k], 6)
        fused.append(c)
    return fused[:top_k * 2]


def _diversify(chunks: list[dict], router: RouterResult, top_k: int) -> list[dict]:
    if router.intent in (QueryIntent.ARTICLE_EXACT, QueryIntent.ARTICLE_RANGE):
        order = ["atom","article","structured","context_window","group","summary","section","paragraph"]
    elif router.intent == QueryIntent.TOPIC:
        order = ["summary","section","context_window","group","atom","article","structured","paragraph"]
    else:
        return chunks[:top_k]

    buckets = {t: [] for t in order}
    others  = []
    for c in chunks:
        t = c.get("type", "")
        (buckets[t] if t in buckets else others).append(c)

    result: list[dict] = []
    seen_h: set[str]   = set()

    def add(lst):
        for c in lst:
            if len(result) >= top_k: break
            h = c.get("header", c.get("articles", ""))[:60]
            if h not in seen_h:
                seen_h.add(h); result.append(c)

    for t in order: add(buckets[t])
    add(others); add(chunks)
    return result[:top_k]


# =============================================================================
#  §5  Main Entry Point
# =============================================================================

def search_similar_chunks(query: str, top_k: int = TOP_K) -> list[dict]:
    logger.info(f"[RAG] '{query[:80]}'")
    router = route_query(query)
    logger.info(f"[RAG] intent={router.intent.value} nums={router.art_nums} kw={router.keywords[:3]}")

    pg_res: list[dict] = []
    if router.intent != QueryIntent.GENERAL:
        pg_res = structured_search(query, router, top_k=top_k * 2)

    vec_res = semantic_search(query, router, top_k=top_k * 2)

    if pg_res and vec_res:
        fused = _rrf_fuse(pg_res, vec_res, top_k)
        final = _diversify(fused, router, top_k)
    elif pg_res:
        pg_res.sort(key=lambda x: x.get("pg_rank", 0), reverse=True)
        final = _diversify(pg_res, router, top_k)
    elif vec_res:
        vec_res.sort(key=lambda x: x.get("vec_score", 0), reverse=True)
        final = _diversify(vec_res, router, top_k)
    else:
        logger.warning("[RAG] لا نتائج")
        return []

    # ── إعادة الترتيب: رفع المواد المطابقة تماماً إلى الأعلى ──
    if router.intent == QueryIntent.ARTICLE_EXACT and router.art_nums:
        exact_set = set(router.art_nums)

        def _rerank_key(chunk):
            arts_raw = chunk.get("articles", "")
            chunk_nums = (
                {int(x) for x in re.findall(r'\d+', arts_raw.translate(_AR2LA))}
                if arts_raw else set()
            )
            is_exact_pg = (
                bool(chunk_nums & exact_set)
                and chunk.get("source") in ("postgresql", "hybrid", "structured")
            )
            return (0 if is_exact_pg else 1, -chunk.get("score", 0))

        final.sort(key=_rerank_key)

    # ── درجة الثقة الموحّدة ──
    for chunk in final:
        score     = chunk.get("score", 0)
        vec_score = chunk.get("vec_score", 0)
        source    = chunk.get("source", "")
        arts_raw  = chunk.get("articles", "")
        chunk_nums = (
            {int(x) for x in re.findall(r'\d+', arts_raw.translate(_AR2LA))}
            if arts_raw else set()
        )
        exact_hit = (
            router.intent == QueryIntent.ARTICLE_EXACT
            and bool(chunk_nums & set(router.art_nums))
            and source in ("postgresql", "hybrid", "structured")
        )
        if exact_hit:
            confidence = "high"
        elif score >= 0.008 or vec_score >= 0.55:
            confidence = "high"
        elif score >= 0.004 or vec_score >= 0.35:
            confidence = "medium"
        else:
            confidence = "low"
        chunk["confidence"] = confidence

    logger.info(
        f"[RAG] ✓ {len(final)} نتيجة | "
        f"pg={sum(1 for c in final if c.get('source') in ('postgresql','hybrid'))} | "
        f"vec={sum(1 for c in final if c.get('source')=='pinecone')} | "
        f"high={sum(1 for c in final if c.get('confidence')=='high')}"
    )
    return final[:top_k]


# =============================================================================
#  §6  Embedding
# =============================================================================

def embed_text(text: str) -> list[float]:
    # حد آمن: 3000 حرف عربي ≈ 1500 token (بعيد عن حد 8192)
    # النص العربي من Presentation Form PDFs يكون مضغوطاً أكثر
    MAX_CHARS = 3000
    text_to_embed = text[:MAX_CHARS]

    for attempt in range(4):
        try:
            return client.embeddings.create(
                model="text-embedding-3-large",
                input=text_to_embed,
            ).data[0].embedding
        except Exception as e:
            err = str(e).lower()
            if "maximum context length" in err or "8192" in err:
                # قلّل الحد أكثر وأعد المحاولة
                MAX_CHARS = MAX_CHARS // 2
                text_to_embed = text[:MAX_CHARS]
                logger.warning(f"[embed] تجاوز الـ tokens — قلّل إلى {MAX_CHARS} حرف")
            elif any(x in err for x in ("rate", "429", "capacity")):
                wait = 2 ** attempt
                logger.warning(f"Rate limit — wait {wait}s")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("embed_text failed after 4 attempts")


# =============================================================================
#  §7  Document Storage
# =============================================================================

def store_document_in_pinecone(doc_id: int, text: str, doc_title: str = "") -> int:
    logger.info(f"[Store] #{doc_id} '{doc_title}'")
    pc_count  = _store_pinecone(doc_id, text, doc_title)
    art_count = _store_legal_articles(doc_id, text, doc_title)

    try:
        from .models import Document
        Document.objects.filter(pk=doc_id).update(
            articles_count=art_count,
            pinecone_chunks=pc_count,
            is_indexed=(pc_count > 0 or art_count > 0),
        )
    except Exception as e:
        logger.warning(f"[Store] stats update failed: {e}")

    logger.info(f"[Store] #{doc_id}: Pinecone={pc_count} | LegalArticle={art_count}")
    return pc_count


def _store_pinecone(doc_id: int, text: str, doc_title: str) -> int:
    chunks = smart_chunk(text, doc_title=doc_title)
    if not chunks: return 0

    vectors    = []
    seen_hashes: set[str] = set()   # حماية من chunks متطابقة في نفس الرفع
    for c in chunks:
        try:
            # إزالة المحتوى المكرر (نفس النص حرفياً)
            ch = hashlib.md5(c["text"].encode("utf-8")).hexdigest()
            if ch in seen_hashes:
                continue
            seen_hashes.add(ch)

            emb = embed_text(c["text"])
            raw_arts = c.get("articles", "")
            # الأرقام كـ strings للـ $in filter (نحوّل العربية أيضاً)
            art_nums_str = [str(n) for n in re.findall(r'\d+', raw_arts.translate(_AR2LA))] if raw_arts else []
            vectors.append({
                "id": f"{doc_id}-{c['id']}",
                "values": emb,
                "metadata": {
                    "doc_id":     str(doc_id),
                    "doc_title":  doc_title,
                    "type":       c["type"],
                    "header":     c.get("header", "")[:120],
                    "articles":   raw_arts,
                    "art_nums":   art_nums_str,
                    "text":       c["text"],
                    "char_count": len(c["text"]),
                },
            })
        except Exception as e:
            logger.error(f"[Pinecone] chunk {c['id']} failed: {e}")

    total = 0
    for i in range(0, len(vectors), BATCH_SIZE):
        batch = vectors[i:i + BATCH_SIZE]
        try:
            index.upsert(vectors=batch)
            total += len(batch)
        except Exception as e:
            logger.error(f"[Pinecone] batch failed: {e}")
        if i + BATCH_SIZE < len(vectors):
            time.sleep(0.3)
    return total


def _store_legal_articles(doc_id: int, text: str, doc_title: str) -> int:
    from .models import LegalArticle, Document

    cleaned = clean_text(text)
    if len(ARTICLE_RE.findall(cleaned)) < 1:
        logger.info(f"[LegalArticle] #{doc_id}: no articles — skip")
        return 0

    tree = _parse_document(cleaned)
    if not tree: return 0

    try:
        doc_obj = Document.objects.get(pk=doc_id)
    except Exception as e:
        logger.error(f"[LegalArticle] doc #{doc_id} not found: {e}")
        return 0

    to_create: list = []
    order = 0
    # مادة رقم → نص (لدمج النصوص المكررة بدل تجاهلها أو إعادة ترقيمها)
    seen_nums: dict[int, int] = {}   # num_int → index في to_create
    skipped = 0

    for section in tree:
        bc = section["breadcrumb"]
        for art in section["articles"]:
            art_text = art["text"].strip()
            num_int  = art.get("num_int") or (9000 + order)

            # تجاهل مواد نصها قصير جداً (< 15 حرف) — غالباً مراجع أو عناوين
            if len(art_text) < 15:
                skipped += 1
                continue

            if num_int in seen_nums:
                # نفس الرقم ظهر مرتين: ادمج النص بدل إنشاء سجل جديد
                prev_idx = seen_nums[num_int]
                prev_text = to_create[prev_idx].text
                if art_text not in prev_text:
                    to_create[prev_idx].text = prev_text + "\n" + art_text
                skipped += 1
                continue

            seen_nums[num_int] = len(to_create)
            to_create.append(LegalArticle(
                doc=doc_obj,
                article_number=num_int,
                article_number_display=art["num"],
                section_path=bc,
                text=art_text,
                order_in_doc=order,
            ))
            order += 1

    if skipped:
        logger.info(f"[LegalArticle] #{doc_id}: تجاوز {skipped} مدخل مكرر/قصير")

    if not to_create: return 0

    with transaction.atomic():
        LegalArticle.objects.filter(doc_id=doc_id).delete()
        LegalArticle.objects.bulk_create(to_create, batch_size=200)

    count = LegalArticle.objects.filter(doc_id=doc_id).count()
    logger.info(f"[LegalArticle] #{doc_id}: {count} مادة")
    return count


# =============================================================================
#  §8  Text Utilities
# =============================================================================

def normalize_arabic_pdf(text: str) -> str:
    """
    يعالج نصاً عربياً مستخرجاً من PDF يستخدم Unicode Presentation Forms
    (U+FE70–U+FEFF) بدلاً من Unicode العادي.

    هذه الـ PDFs شائعة في المستندات القانونية العربية القديمة.
    العلامة: الحروف تبدو مثل ﻝ ﻤ ﺍ ﺩ بدلاً من ل م ا د

    الخطوات:
      1. NFKC normalization: تحول Presentation Forms → Unicode عادي
         مثال: ﺍﻝﻤﺎﺩﺓ → المادة
      2. إزالة حرف 'ي' الفاصل (artifact خاص بهذا النوع من PDF)
         مثال: ي١المادةي → المادة ١
      2b. إزالة تكرار 'ه' الفاصل في ترويسات الأقسام
         مثال: هههههالبابهالأول → الباب الأول
      3a. إصلاح صيغة المادة بالسلاش مع عكس الأرقام (PDF البصري)
         مثال: -/001/المادة → المادة 100  (الأرقام مخزّنة معكوسة بصرياً)
      3b. إصلاح نمط 'رقم + المادة' المباشر مع عكس الأرقام المتعددة
         مثال: ٠١المادة → المادة 10
      4. فصل الكلمات الملتصقة بحروف عربية وسيطة
    """
    # 1. NFKC
    text = unicodedata.normalize('NFKC', text)

    # 2. استبدال 'ي' الفاصلة بمسافة — فقط عند تكرار ي (separator واضح)
    #    أو عند بداية/نهاية كلمة (ليست حرف ي مشروع في التي/في/الذي/إلخ)
    # 2a. ييي متكررة = فاصل مؤكد → مسافة
    text = re.sub(r'ي{2,}', ' ', text)
    # 2b. ي بين رقم وحرف أو حرف ورقم (artifact بجانب أرقام المواد)
    text = re.sub(r'([٠-٩\d])ي([ا-ي])', r'\1 \2', text)
    text = re.sub(r'([ا-ي])ي([٠-٩\d])', r'\1 \2', text)
    # 2c. ي في بداية السطر (مباشرة قبل حرف عربي) → مسافة
    text = re.sub(r'^ي([ا-ي])', r' \1', text, flags=re.MULTILINE)

    # 2b. إزالة تكرار 'ه' المستخدم كفاصل في ترويسات الأقسام
    #     مثال: هههههالبابههالأول → الباب الأول
    text = re.sub(r'ه{2,}', ' ', text)

    # 3a. إصلاح صيغة السلاش المعكوسة: -/٠٠١/المادة → المادة 100
    #     في PDFs البصرية (visual-order) الأرقام المتعددة الخانات مخزّنة بترتيب
    #     معكوس: "001" يعني المادة 100، "21" يعني المادة 12، إلخ.
    def _fix_slash_art(m):
        raw = re.sub(r'[^٠-٩\d]', '', m.group(0))   # استخرج الأرقام فقط
        latin = raw.translate(_AR2LA)                  # عربي → لاتيني
        corrected = latin[::-1].lstrip('0') or '0'    # اعكس الخانات
        return f'المادة {corrected}'
    # يطابق: .-/٠٠١/المادة  أو  -/٦/المادة  أو  .-/.٥١/المادة
    text = re.sub(r'[-\./]+[٠-٩\d\.]+[-\./]+\s*المادة', _fix_slash_art, text)

    # 3b. إصلاح نمط الرقم المباشر قبل المادة مع عكس الأرقام المتعددة
    #     مثال: ٠١المادة → المادة 10  |  ١المادة → المادة 1
    def _fix_inline_art(m):
        raw = m.group(1).translate(_AR2LA)
        if len(raw) <= 1:
            corrected = raw                            # رقم واحد: لا حاجة للعكس
        else:
            corrected = raw[::-1].lstrip('0') or '0'  # اعكس الخانات
        return f'المادة {corrected}'
    text = re.sub(r'([٠-٩\d]+)\s*(المادة)', _fix_inline_art, text)

    # 4. فصل أي كلمتين ملتصقتين بدون مسافة بعد حروف الربط الشائعة
    text = re.sub(r'([ا-ي]{3,})(ال[ا-ي]{2,})', r'\1 \2', text)

    return text


def is_presentation_form_pdf(text: str) -> bool:
    """يكتشف إن كان النص مستخرجاً من PDF يستخدم Presentation Forms."""
    if not text:
        return False
    # عيّنة من أول 500 حرف
    sample = text[:500]
    pf_chars = sum(1 for ch in sample if 0xFB50 <= ord(ch) <= 0xFEFF)
    return pf_chars / max(len(sample), 1) > 0.1  # أكثر من 10% presentation forms



def _extract_with_pymupdf(pdf_path: str) -> str:
    """استخراج النص بـ pymupdf — أفضل دعم لخطوط التشفير المخصصة."""
    import fitz  # pymupdf
    pages = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            try:
                t = page.get_text("text") or ""
                if t.strip():
                    pages.append(t)
            except Exception as e:
                logger.warning(f"[pymupdf] page {i+1}: {e}")
    return "\n\n".join(pages)


def _extract_with_pypdf2(pdf_path: str) -> str:
    """استخراج النص بـ PyPDF2 — احتياطي."""
    pages = []
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
                if t.strip():
                    pages.append(t)
            except Exception as e:
                logger.warning(f"[PyPDF2] page {i+1}: {e}")
    return "\n\n".join(pages)


def _text_quality(text: str) -> float:
    """
    يقيّم جودة النص المستخرج ويميّز بين:
      • Presentation Forms (U+FB50–U+FEFF): قيمة عالية → يُفضَّل PyPDF2
      • Arabic Unicode عادي: حسب نسبة الحروف الأساسية
      • تشفير خط مخصص (دياكريتيك كحروف): قيمة منخفضة
    """
    if not text:
        return 0.0
    sample = text[:2000]
    # Presentation Forms — PDFs قانونية عربية قديمة (نعالجها بـ NFKC + PyPDF2)
    pf_chars = sum(1 for c in sample if 0xFB50 <= ord(c) <= 0xFEFF)
    pf_ratio = pf_chars / max(len(sample), 1)
    if pf_ratio > 0.08:
        return 0.75  # جيد — NFKC + normalize_arabic_pdf تعالجه

    # Arabic Unicode عادي
    core_ar = sum(1 for c in sample if 'ء' <= c <= 'غ' or 'ف' <= c <= 'ي')
    diacrit = sum(1 for c in sample if 'ؐ' <= c <= 'ٟ')
    total   = max(len([c for c in sample if c.strip()]), 1)
    # تشفير خط مخصص: دياكريتيك تُستخدم بدل حروف أساسية
    if diacrit > core_ar * 0.5:
        return 0.25
    return min(core_ar / total, 0.95)


def extract_pdf_text(pdf_path: str) -> str:
    """
    يستخرج النص من PDF مع إعطاء الأولوية لـ PyPDF2:
      1. يجرب PyPDF2 أولاً (يستخرج نصاً أكثر للـ PDFs العربية القانونية)
      2. إذا فشل أو النص قصير جداً (< 5000 حرف) → يجرب pymupdf
      3. يختار الأطول نصاً عند تساوي الجودة
    """
    if not Path(pdf_path).exists():
        raise FileNotFoundError(pdf_path)

    fitz_text  = ""
    pypdf_text = ""
    fitz_q     = 0.0
    pypdf_q    = 0.0

    # ── المحاولة الأولى: PyPDF2 ──
    try:
        pypdf_text = _extract_with_pypdf2(pdf_path)
        pypdf_q    = _text_quality(pypdf_text)
        logger.info(f"[PDF/PyPDF2] {len(pypdf_text)} حرف | جودة={pypdf_q:.2f}")
    except Exception as e:
        logger.warning(f"[PDF/PyPDF2] فشل: {e}")

    # ── المحاولة الثانية: pymupdf (احتياطي أو مقارنة) ──
    if len(pypdf_text) < 5000:
        try:
            fitz_text = _extract_with_pymupdf(pdf_path)
            fitz_q    = _text_quality(fitz_text)
            logger.info(f"[PDF/pymupdf] {len(fitz_text)} حرف | جودة={fitz_q:.2f}")
        except ImportError:
            logger.warning("[PDF] pymupdf غير مثبت")
        except Exception as e:
            logger.warning(f"[PDF/pymupdf] فشل: {e}")

    # اختر النص المناسب:
    #   • Presentation Forms (pypdf_q >= 0.7): PyPDF2 دائماً
    #   • عند التساوي أو PyPDF2 أطول: اختر PyPDF2
    #   • pymupdf أفضل: استخدمه
    if pypdf_q >= 0.7 and pypdf_text:
        full = pypdf_text
        src  = "PyPDF2 (Presentation Forms)"
    elif pypdf_text and len(pypdf_text) >= len(fitz_text):
        full = pypdf_text
        src  = "PyPDF2"
    elif fitz_text:
        full = fitz_text
        src  = "pymupdf"
    else:
        full = pypdf_text or fitz_text
        src  = "fallback"

    pages = len([p for p in full.split("\n\n") if p.strip()])
    logger.info(f"[PDF] {src} → {len(full)} حرف | ~{pages} صفحة")
    return full



def clean_text(text: str) -> str:
    """
    تنظيف مُحسَّن يُصلح أكثر كسور PyPDF2 شيوعاً.
    يكتشف تلقائياً نصوص Presentation Forms ويعالجها.
    """
    # ── اكتشاف ومعالجة Presentation Forms (PDFs قديمة) ──
    if is_presentation_form_pdf(text):
        logger.info("[clean_text] اكتُشف PDF من نوع Presentation Forms — تطبيق NFKC normalization")
        text = normalize_arabic_pdf(text)

    # أحرف تحكم
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # ── إصلاح "المادة" المكسورة ── (أهم إصلاح للمواد المفقودة)
    text = re.sub(r'ال\s*م\s*ا\s*د\s*ة', 'المادة', text)
    text = re.sub(r'(?<![أ-ي])م\s*ا\s*د\s*ة', 'مادة', text)

    # إصلاح "ا لـ" المنفصلة
    text = re.sub(r'\bا\s+ل([أإآءئؤا-ي])', r'ال\1', text)

    # إصلاح كسور المصطلحات القانونية
    _fixes = [
        (r'الأ\s+حوال','الأحوال'),(r'الأ\s+هلية','الأهلية'),
        (r'الأ\s+ولى','الأولى'),  (r'الأ\s+صول','الأصول'),
        (r'الأ\s+حكام','الأحكام'),(r'الإ\s+رث','الإرث'),
        (r'الإ\s+يجاب','الإيجاب'),(r'الن\s+فقة','النفقة'),
        (r'الو\s+صية','الوصية'),  (r'الز\s+واج','الزواج'),
        (r'الط\s+لاق','الطلاق'),  (r'الح\s+ضانة','الحضانة'),
        (r'الم\s+هر','المهر'),    (r'الو\s+ارث','الوارث'),
        (r'الت\s+ركة','التركة'),  (r'الم\s+يراث','الميراث'),
        (r'الم\s+رأة','المرأة'),  (r'الز\s+وجة','الزوجة'),
        (r'الق\s+اضي','القاضي'),  (r'الع\s+قد','العقد'),
        (r'الع\s+دة','العدة'),    (r'الو\s+لي','الولي'),
        (r'الو\s+كيل','الوكيل'),  (r'الش\s+رط','الشرط'),
        (r'الت\s+فريق','التفريق'),(r'الن\s+سب','النسب'),
        (r'الك\s+تاب','الكتاب'),  (r'الب\s+اب','الباب'),
        (r'الف\s+صل','الفصل'),
        # قانون تجاري
        (r'الش\s+ركة','الشركة'),  (r'الت\s+اجر','التاجر'),
        (r'الت\s+جارة','التجارة'),(r'الس\s+ند','السند'),
        (r'الص\s+رف','الصرف'),    (r'الش\s+يك','الشيك'),
        (r'الإ\s+فلاس','الإفلاس'),(r'الت\s+صفية','التصفية'),
        (r'الإ\s+جراء','الإجراء'),(r'الت\s+حكيم','التحكيم'),
        (r'الع\s+لامة','العلامة'),(r'الب\s+راءة','البراءة'),
        (r'الت\s+أمين','التأمين'),(r'الن\s+قل','النقل'),
        (r'الس\s+فينة','السفينة'),(r'الط\s+يران','الطيران'),
        # تنظيف artifact "رجوع" و"انتهى" الشائعة في PDFs القانونية العربية
        (r'\s+رجوع\s*$',''),      (r'\s+انتهى\s*$',''),
        (r'^\s*رجوع\s*',''),
    ]
    for p, r in _fixes:
        text = re.sub(p, r, text)

    # إزالة "رجوع" بعد رقم المادة
    text = re.sub(r'(المادة\s*[\d٠-٩]+)\s+رجوع\b', r'\1', text)

    # إزالة أرقام الصفحات المنفردة
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)

    # توحيد
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    return text.strip()


# =============================================================================
#  §9  Document Parser — مُحسَّن
# =============================================================================

def _parse_document(text: str) -> list[dict]:
    """
    التحسينات على النسخة الأصلية:
    - search() بدل match() لالتقاط مادة في منتصف السطر
    - تخزين num_int مع كل مادة لـ LegalArticle
    - إصلاح عدم إنشاء قسم عند بداية الكتاب/الباب
    - تجاهل عناوين قصيرة وهمية لا تستحق قسماً
    """
    lines            = text.split('\n')
    tree: list[dict] = []
    path: list[str]  = []
    current_section  = None
    current_article  = None

    def flush_art():
        nonlocal current_article
        if current_article and current_section is not None:
            t = current_article["text"].strip()
            if len(t) >= 10:
                current_section["articles"].append(current_article)
        current_article = None

    def flush_sec():
        nonlocal current_section
        if current_section and current_section["articles"]:
            tree.append(current_section)
        current_section = None

    def new_sec(title: str):
        nonlocal current_section
        flush_art()
        flush_sec()
        bc = " > ".join(path + [title]).strip(" >")
        current_section = {"title": title, "breadcrumb": bc, "articles": []}

    new_sec("عام")

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # ── هيكل (كتاب / باب / فصل) ── يدعم أي مسافات بادئة أو أحرف نظيفة
        line = re.sub(r'^[\s ه./-]+', '', line)   # تنظيف بوادر ه والرموز المتبقية
        if not line:
            continue
        sm = re.match(r'^(الكتاب|الباب|الفصل)\s+.+', line)
        if sm:
            lw = sm.group(1)
            flush_art()
            flush_sec()
            path = (
                [line]           if lw == 'الكتاب' else
                path[:1] + [line] if lw == 'الباب'  else
                path[:2] + [line]
            )
            bc = " > ".join(path).strip(" >")
            current_section = {"title": line, "breadcrumb": bc, "articles": []}
            continue

        # ── مادة (search يلتقط مادة في أي موضع بالسطر) ──
        am = ARTICLE_RE.search(line)

        # عنوان قسم موضوعي: قصير + عربي + بلا أرقام + بلا علامات ترقيم
        if (not am
                and 3 <= len(line) <= 55
                and re.match(r'^[أ-ي]', line)
                and not re.search(r'[.،؟!\d٠-٩]', line)
                and not re.match(r'^(الكتاب|الباب|الفصل|مادة|المادة)', line)):
            new_sec(line)
            continue

        if am:
            # ── تحقق: هل "المادة N" مرجع داخلي في نص مادة؟
            # المرجع الداخلي يسبقه كلمات مثل "وفقاً/بموجب/أحكام/المنصوص..."
            # بينما رأس المادة الحقيقي يبدأ بها مباشرة أو بفاصل بسيط
            _XREF = {'وفقاً','بموجب','المنصوص','المشار','المذكور','بأحكام',
                     'لأحكام','نص','ونص','الواردة','المقررة','المبينة',
                     'المحددة','المرقمة','المشمولة','المتعلقة'}
            prefix_before = line[:am.start()].strip()
            is_xref = any(w in prefix_before for w in _XREF)
            if is_xref:
                # مرجع داخلي — أضفه لنص المادة الحالية
                if current_article:
                    current_article["text"] += "\n" + line
                continue

            flush_art()
            if current_section is None:
                new_sec("عام")

            art_label = re.sub(r'\s+', ' ', am.group().strip())
            num_int   = _extract_num(art_label)

            # النص بعد label المادة في نفس السطر
            inline = line[am.end():].strip()
            initial = line if not inline else f"{art_label} {inline}"

            current_article = {
                "num":        art_label,
                "num_int":    num_int,
                "text":       initial,
                "breadcrumb": current_section["breadcrumb"],
                "full_path":  f"{current_section['breadcrumb']} > {art_label}",
            }
            continue

        if current_article:
            current_article["text"] += "\n" + line

    flush_art()
    flush_sec()
    return tree


# =============================================================================
#  §10  Chunking (للـ Pinecone)
# =============================================================================

def _build_hierarchical_chunks(tree: list[dict], doc_title: str) -> list[dict]:
    chunks: list[dict] = []
    idx = 0

    for section in tree:
        arts = section["articles"]
        bc   = section["breadcrumb"]
        if not arts:
            continue

        # SECTION
        sec_body = f"# {bc}\n\n" + "\n\n".join(
            f"{a['num']}\n{a['text'].strip()}" for a in arts
        )
        if len(sec_body) <= MAX_SECTION_SIZE and len(arts) >= 2:
            chunks.append({
                "id": f"section-{idx}", "type": "section",
                "text": sec_body, "doc_title": doc_title,
                "header": bc, "articles": ", ".join(a['num'] for a in arts),
            })
            idx += 1

        # GROUP
        step = max(1, GROUP_SIZE - GROUP_OVERLAP)
        for i in range(0, len(arts), step):
            grp = arts[i: i + GROUP_SIZE]
            if len(grp) < 2: break
            grp_body = f"# {bc}\n\n" + "\n\n".join(
                f"{a['num']}\n{a['text'].strip()}" for a in grp
            )
            chunks.append({
                "id": f"group-{idx}", "type": "group",
                "text": grp_body, "doc_title": doc_title,
                "header": bc, "articles": ", ".join(a['num'] for a in grp),
            })
            idx += 1

        # ARTICLE
        for art in arts:
            body = f"# {art['breadcrumb']}\n\n{art['num']}\n{art['text'].strip()}"
            if len(body) >= MIN_CHUNK_SIZE:
                chunks.append({
                    "id": f"article-{idx}", "type": "article",
                    "text": body, "doc_title": doc_title,
                    "header": art["full_path"], "articles": art["num"],
                })
                idx += 1

    return chunks


def _chunk_paragraphs(text: str, doc_title: str) -> list[dict]:
    # حد آمن: 2500 حرف ≈ 1200 token (مناسب للنصوص المضغوطة)
    MAX, OVER = 2500, 200
    # محاولة التقسيم بفقرات أولاً، ثم بأسطر إن فشل
    raw = re.split(r'\n{2,}', text)
    if len(raw) <= 2:
        # النص مضغوط بدون فراغات — قسّم بالأسطر
        raw = text.split('\n')
    if len(raw) <= 2:
        # لا فراغات ولا أسطر — قسّم بالجمل (نقطة أو نقطة عربية)
        raw = re.split(r'(?<=[.،؟])\s+', text)
    if len(raw) <= 2:
        # آخر خيار: قسّم بالحجم مباشرة
        raw = [text[i:i+MAX] for i in range(0, len(text), MAX - OVER)]

    chunks, buf, idx = [], "", 0
    for para in raw:
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= MAX:
            buf = (buf + "\n\n" + para).strip()
        else:
            if len(buf) >= MIN_CHUNK_SIZE:
                chunks.append({
                    "id": f"para-{idx}", "type": "paragraph",
                    "text": buf, "doc_title": doc_title,
                    "header": buf[:80].split('\n')[0], "articles": "",
                })
                idx += 1
            buf = ((buf[-OVER:] + "\n\n" + para) if buf else para).strip()
    if len(buf) >= MIN_CHUNK_SIZE:
        chunks.append({
            "id": f"para-{idx}", "type": "paragraph",
            "text": buf, "doc_title": doc_title,
            "header": buf[:80].split('\n')[0], "articles": "",
        })
    return chunks



def smart_chunk(text: str, doc_title: str = "") -> list[dict]:
    """نقطة دخول الـ chunking للـ Pinecone."""
    text = clean_text(text)
    if not text: return []
    art_count = len(ARTICLE_RE.findall(text))
    logger.info(f"[Chunk] {art_count} مادة في \'{doc_title}\'")
    if art_count == 0:
        logger.warning(f"[Chunk] 0 مواد — أول 300 حرف: {repr(text[:300])}")
    if art_count >= 2:
        tree   = _parse_document(text)
        chunks = _build_hierarchical_chunks(tree, doc_title)
        if chunks:
            types = {}
            for c in chunks:
                types[c["type"]] = types.get(c["type"], 0) + 1
            logger.info(f"[Chunk/hierarchical] {len(chunks)}: {types}")
            return chunks
    chunks = _chunk_paragraphs(text, doc_title)
    logger.info(f"[Chunk/para] {len(chunks)}")
    return chunks