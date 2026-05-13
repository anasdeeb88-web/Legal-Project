"""
RAG (Retrieval-Augmented Generation) utilities.
نظام استرجاع هرمي ثلاثي المستويات — مُحسَّن للقوانين والوثائق العربية.

مستويات الـ chunking:
  1. section  — كل المواد في قسم واحد (للأسئلة الموضوعية العامة)
  2. group    — 3 مواد متتالية مع تداخل (للأسئلة التي تحتاج سياقاً)
  3. article  — مادة واحدة + breadcrumb (للبحث الدقيق عن نص بعينه)
"""

import re
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import PyPDF2
from openai import OpenAI
from pinecone import Pinecone
from django.conf import settings

logger = logging.getLogger(__name__)

# ── تهيئة عملاء API ──
client = OpenAI(api_key=settings.OPENAI_API_KEY)
pc    = Pinecone(api_key=settings.PINECONE_API_KEY)
index = pc.Index(settings.PINECONE_INDEX_NAME)

# ── الثوابت ──
MAX_SECTION_SIZE = 4000   # أقصى حجم لـ section chunk بالحروف
GROUP_SIZE       = 3      # عدد المواد في كل group chunk
GROUP_OVERLAP    = 1      # تداخل مادة واحدة بين المجموعات
MIN_CHUNK_SIZE   = 60     # حد أدنى للـ chunk
BATCH_SIZE       = getattr(settings, 'RAG_BATCH_SIZE', 50)
TOP_K            = getattr(settings, 'RAG_TOP_K_RESULTS', 5)

# ── أنماط التعرف على البنية ──
ARTICLE_RE = re.compile(
    r'(?:(?:الـ?\s*مادة|الم\s*ادة|(?<!\w)مادة)\s*'
    r'(?:[٠-٩0-9]+|'
    r'الأولى?|الثانية?|الثالثة?|الرابعة?|الخامسة?|'
    r'السادسة?|السابعة?|الثامنة?|التاسعة?|العاشرة?|'
    r'[أ-ي]+))',
    re.UNICODE
)

STRUCTURAL_RE = re.compile(
    r'^(الكتاب|الباب|الفصل)\s.+',
    re.MULTILINE
)

SECTION_TITLE_RE = re.compile(
    r'^(?!المادة|الكتاب|الباب|الفصل|أ\s*ـ|ب\s*ـ|[0-9])'
    r'[أ-ي][أ-ي\s]{2,40}$',
    re.MULTILINE
)


# =============================================================================
# 1.  استخراج النص
# =============================================================================

def extract_text_from_pdf(pdf_path: str) -> str:
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"ملف PDF غير موجود: {pdf_path}")
    pages = []
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                try:
                    text = page.extract_text() or ""
                    if text.strip():
                        pages.append(text)
                except Exception as e:
                    logger.warning(f"فشل استخراج الصفحة {i+1}: {e}")
    except PyPDF2.PdfReadError as e:
        logger.error(f"فشل قراءة PDF: {e}")
        raise
    full_text = "\n\n".join(pages)
    logger.info(f"استُخرج {len(full_text)} حرف من PDF ({len(pages)} صفحة)")
    return full_text


# =============================================================================
# 2.  تنظيف النص
# =============================================================================

def clean_text(text: str) -> str:
    """
    تنظيف جراحي دقيق — يُصلح مخرجات PyPDF2 دون أن يدمج كلمات منفصلة.
    """
    # إزالة أحرف تحكم
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # إصلاح "الم ادة" → "المادة"
    text = re.sub(r'الم\s+ادة', 'المادة', text)

    # إصلاح "ا لـ" المنفصلة (بداية الكلمة فقط)
    text = re.sub(r'\bا\s+ل([أإآءئؤا-ي])', r'ال\1', text)

    # إصلاح كسور شائعة في القوانين السورية
    _fixes = [
        (r'الأ\s+حوال',  'الأحوال'),  (r'الأ\s+هلية',  'الأهلية'),
        (r'الأ\s+ولى',   'الأولى'),   (r'الأ\s+صول',   'الأصول'),
        (r'الأ\s+حكام',  'الأحكام'),  (r'الإ\s+رث',    'الإرث'),
        (r'الإ\s+يجاب',  'الإيجاب'),  (r'الت\s+رتيب',  'الترتيب'),
        (r'الن\s+فقة',   'النفقة'),   (r'الو\s+صية',   'الوصية'),
        (r'الز\s+واج',   'الزواج'),   (r'الط\s+الق',   'الطالق'),
        (r'الح\s+ضانة',  'الحضانة'),  (r'الم\s+هر',    'المهر'),
        (r'الو\s+ارث',   'الوارث'),   (r'الت\s+ركة',   'التركة'),
        (r'الم\s+يراث',  'الميراث'),  (r'الم\s+رأة',   'المرأة'),
        (r'الز\s+وجة',   'الزوجة'),   (r'الق\s+اضي',   'القاضي'),
        (r'الع\s+قد',    'العقد'),    (r'الع\s+دة',    'العدة'),
        (r'الو\s+لي',    'الولي'),    (r'الو\s+كيل',   'الوكيل'),
        (r'الش\s+رط',    'الشرط'),    (r'الت\s+فريق',  'التفريق'),
        (r'الم\s+خالعة', 'المخالعة'), (r'الن\s+سب',    'النسب'),
    ]
    for pattern, replacement in _fixes:
        text = re.sub(pattern, replacement, text)

    # إزالة "رجوع" بعد رقم المادة
    text = re.sub(r'(المادة\s*\d+)\s+رجوع\b', r'\1', text)
    text = re.sub(r'(المادة\s*[\u0600-\u06ff]+)\s+رجوع\b', r'\1', text)

    # إزالة أرقام الصفحات المنفردة
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)

    # توحيد الأسطر والمسافات
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    return text.strip()


# =============================================================================
# 3.  تحليل بنية الوثيقة (Document Parser)
# =============================================================================

def _parse_document(text: str) -> List[Dict]:
    """
    يُحلّل النص ويُعيد شجرة:
    [{ title, breadcrumb, articles: [{num, text, path}] }]
    """
    lines = text.split('\n')
    tree   = []
    path   = []            # [كتاب، باب، فصل]
    current_section = None
    current_article = None

    def _flush_article():
        nonlocal current_article
        if current_article and current_section is not None:
            current_section["articles"].append(current_article)
        current_article = None

    def _flush_section():
        nonlocal current_section
        if current_section and current_section["articles"]:
            tree.append(current_section)
        current_section = None

    def _new_section(title: str):
        nonlocal current_section
        _flush_article()
        _flush_section()
        breadcrumb = " > ".join(path + [title]).strip(" >")
        current_section = {"title": title, "breadcrumb": breadcrumb, "articles": []}

    # ── مقطع افتراضي لو ما في عنوان قسم ──
    _new_section("عام")

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # ── الكتاب / الباب / الفصل ──
        struct_m = re.match(r'^(الكتاب|الباب|الفصل)\s+.+', line)
        if struct_m:
            level_word = struct_m.group(1)
            if level_word == 'الكتاب':
                path = [line]
            elif level_word == 'الباب':
                path = path[:1] + [line]
            else:
                path = path[:2] + [line]
            continue

        # ── عنوان قسم موضوعي ──
        art_m = ARTICLE_RE.match(line)
        is_structural = bool(struct_m)
        is_subsection = bool(re.match(r'^[أ-ي][\s\-ـ]*$', line))  # حرف وحده

        if (not art_m and not is_structural and not is_subsection
                and 3 <= len(line) <= 50
                and re.match(r'^[أ-ي]', line)
                and not re.search(r'[.،؟!0-9]', line)):
            _new_section(line)
            continue

        # ── مادة جديدة ──
        if art_m:
            _flush_article()
            # تأكد في وجود قسم
            if current_section is None:
                _new_section("عام")

            breadcrumb = current_section["breadcrumb"]
            art_num    = art_m.group().strip()
            art_num    = re.sub(r'\s+', ' ', art_num)  # normalize spaces

            current_article = {
                "num":        art_num,
                "text":       line,
                "breadcrumb": breadcrumb,
                "full_path":  f"{breadcrumb} > {art_num}",
            }
            continue

        # ── محتوى المادة ──
        if current_article:
            current_article["text"] += "\n" + line
        # ── محتوى ما قبل أي مادة (مقدمة، تعريفات) ──
        elif current_section is not None:
            pass  # تجاهل المحتوى قبل أول مادة

    # ── تفريغ الأخير ──
    _flush_article()
    _flush_section()

    return tree


# =============================================================================
# 4.  بناء الـ chunks الهرمية الثلاثة
# =============================================================================

def _build_hierarchical_chunks(tree: List[Dict], doc_title: str) -> List[Dict]:
    """
    يبني ثلاثة أنواع من الـ chunks لكل قسم:
      section  — كل مواد القسم (للأسئلة الموضوعية)
      group    — مجموعة 3 مواد متتالية مع تداخل (للسياق)
      article  — مادة واحدة مع breadcrumb (للبحث الدقيق)
    """
    chunks = []
    chunk_idx = 0

    for section in tree:
        arts       = section["articles"]
        breadcrumb = section["breadcrumb"]

        if not arts:
            continue

        # ── TYPE 1: SECTION CHUNK ──
        # كل المواد في القسم مجتمعة
        section_body = f"# {breadcrumb}\n\n"
        section_body += "\n\n".join(
            f"{a['num']}\n{a['text'].strip()}" for a in arts
        )

        if len(section_body) <= MAX_SECTION_SIZE and len(arts) >= 2:
            art_nums = [a['num'] for a in arts]
            chunks.append({
                "id":        f"section-{chunk_idx}",
                "type":      "section",
                "text":      section_body,
                "doc_title": doc_title,
                "header":    breadcrumb,
                "articles":  ", ".join(art_nums),
            })
            chunk_idx += 1

        # ── TYPE 2: GROUP CHUNKS ──
        # مجموعات متداخلة من 3 مواد
        step = max(1, GROUP_SIZE - GROUP_OVERLAP)
        for i in range(0, len(arts), step):
            group = arts[i : i + GROUP_SIZE]
            if len(group) < 2:
                break

            nums       = [a['num'] for a in group]
            group_body = f"# {breadcrumb}\n\n"
            group_body += "\n\n".join(
                f"{a['num']}\n{a['text'].strip()}" for a in group
            )

            chunks.append({
                "id":        f"group-{chunk_idx}",
                "type":      "group",
                "text":      group_body,
                "doc_title": doc_title,
                "header":    breadcrumb,
                "articles":  ", ".join(nums),
            })
            chunk_idx += 1

        # ── TYPE 3: ARTICLE CHUNKS ──
        # مادة واحدة مع breadcrumb كاملة
        for art in arts:
            art_body = (
                f"# {art['breadcrumb']}\n\n"
                f"{art['num']}\n"
                f"{art['text'].strip()}"
            )
            if len(art_body) >= MIN_CHUNK_SIZE:
                chunks.append({
                    "id":        f"article-{chunk_idx}",
                    "type":      "article",
                    "text":      art_body,
                    "doc_title": doc_title,
                    "header":    art['full_path'],
                    "articles":  art['num'],
                })
                chunk_idx += 1

    return chunks


# =============================================================================
# 5.  Fallback: paragraph / sliding window للوثائق غير القانونية
# =============================================================================

def _chunk_paragraphs(text: str, doc_title: str) -> List[Dict]:
    """
    للوثائق غير القانونية أو كـ fallback.
    يتعامل مع PDFs ذات سطر واحد. الحد: 6000 حرف.
    """
    MAX  = 6000
    OVER = 300

    raw_paras = re.split(r'\n{2,}', text)
    if len(raw_paras) <= 1:
        # PDF بسطر واحد — قسّم على \n فردي
        raw_paras = re.split(r'\n', text)
    chunks = []
    buffer = ""
    idx    = 0

    for para in raw_paras:
        para = para.strip()
        if not para:
            continue
        if len(buffer) + len(para) + 2 <= MAX:
            buffer = (buffer + "\n\n" + para).strip()
        else:
            if len(buffer) >= MIN_CHUNK_SIZE:
                chunks.append({
                    "id":        f"para-{idx}",
                    "type":      "paragraph",
                    "text":      buffer,
                    "doc_title": doc_title,
                    "header":    buffer[:80].split('\n')[0],
                    "articles":  "",
                })
                idx += 1
            # overlap
            overlap_text = buffer[-OVER:] if len(buffer) > OVER else buffer
            buffer = (overlap_text + "\n\n" + para).strip()

    if len(buffer) >= MIN_CHUNK_SIZE:
        chunks.append({
            "id":        f"para-{idx}",
            "type":      "paragraph",
            "text":      buffer,
            "doc_title": doc_title,
            "header":    buffer[:80].split('\n')[0],
            "articles":  "",
        })
    return chunks


# =============================================================================
# 6.  الدالة الرئيسية للـ chunking
# =============================================================================

def smart_chunk(text: str, doc_title: str = "") -> List[Dict]:
    """
    يختار استراتيجية الـ chunking المناسبة تلقائياً:
      - إذا وجد مواد قانونية → hierarchical (section + group + article)
      - وإلا → paragraph fallback
    """
    text = clean_text(text)
    if not text:
        logger.warning("النص فارغ بعد التنظيف")
        return []

    # تحقق من وجود مواد قانونية
    article_count = len(ARTICLE_RE.findall(text))
    logger.info(f"[smart_chunk] وجد {article_count} مادة في الوثيقة '{doc_title}'")

    if article_count >= 2:
        tree   = _parse_document(text)
        chunks = _build_hierarchical_chunks(tree, doc_title)
        if chunks:
            types = {}
            for c in chunks:
                types[c['type']] = types.get(c['type'], 0) + 1
            logger.info(f"[hierarchical] {len(chunks)} chunk: {types}")
            return chunks

    # Fallback للوثائق غير القانونية
    chunks = _chunk_paragraphs(text, doc_title)
    logger.info(f"[paragraph] {len(chunks)} chunk")
    return chunks


# =============================================================================
# 7.  التضمين (Embedding)
# =============================================================================

def embed_text(text: str) -> List[float]:
    """
    توليد embedding مع إعادة المحاولة عند تجاوز حد المعدل (rate limit).
    """
    import time

    for attempt in range(4):
        try:
            response = client.embeddings.create(
                model="text-embedding-3-large",
                input=text[:6000]
            )
            return response.data[0].embedding
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "capacity" in err:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                logger.warning(f"Rate limit — انتظر {wait}s ثم أعيد المحاولة ({attempt+1}/4)")
                time.sleep(wait)
            else:
                logger.error(f"فشل توليد التضمين: {e}")
                raise
    raise RuntimeError("فشل توليد التضمين بعد 4 محاولات")


# =============================================================================
# 8.  التخزين في Pinecone
# =============================================================================

def store_document_in_pinecone(doc_id: int, text: str,
                                doc_title: str = "") -> int:
    import time

    logger.info(f"معالجة الوثيقة #{doc_id} '{doc_title}'")

    chunks = smart_chunk(text, doc_title=doc_title)
    if not chunks:
        logger.warning(f"لا توجد مقاطع قابلة للتخزين في الوثيقة #{doc_id}")
        return 0

    vectors = []
    for chunk in chunks:
        try:
            embedding = embed_text(chunk["text"])
            vector_id = f"{doc_id}-{chunk['id']}"

            # استخراج أرقام المواد
            raw_arts = chunk.get("articles", "")
            # قائمة الأرقام الصافية فقط: ["233", "234"] — لـ Pinecone $in filter
            art_nums = re.findall(r'\d+', raw_arts) if raw_arts else []

            vectors.append({
                "id":     vector_id,
                "values": embedding,
                "metadata": {
                    "doc_id":     str(doc_id),
                    "doc_title":  doc_title,
                    "type":       chunk["type"],
                    "header":     chunk.get("header", "")[:120],
                    "articles":   raw_arts,    # "مادة 233, مادة 234" — للعرض
                    "art_nums":   art_nums,    # ["233", "234"] — للفلترة بـ $in
                    "text":       chunk["text"],
                    "char_count": len(chunk["text"]),
                }
            })
        except Exception as e:
            logger.error(f"فشل chunk {chunk['id']}: {e}")

    total = 0
    for i in range(0, len(vectors), BATCH_SIZE):
        batch = vectors[i : i + BATCH_SIZE]
        try:
            index.upsert(vectors=batch)
            total += len(batch)
            logger.debug(f"رُفعت دفعة {i//BATCH_SIZE + 1}: {len(batch)} vector")
        except Exception as e:
            logger.error(f"فشل رفع الدفعة: {e}")
        # فترة راحة قصيرة بين الدفعات لتجنب rate limit
        if i + BATCH_SIZE < len(vectors):
            time.sleep(0.3)

    logger.info(f"الوثيقة #{doc_id}: خُزِّن {total}/{len(vectors)} مقطع")
    return total


# =============================================================================
# 9.  البحث والاسترجاع — Hybrid Search
# =============================================================================


def search_similar_chunks(query: str,
                           top_k: int = TOP_K) -> List[Dict[str, Any]]:
    """
    بحث هجين (Hybrid Search):
    - إذا كان السؤال عن مادة بعينها (رقم) → فلترة مباشرة بـ $in + بحث دلالي
    - إذا كان سؤالاً موضوعياً → بحث دلالي فقط مع تنويع الأنواع
    """
    logger.info(f"بحث RAG: '{query[:60]}'")

    # ── كشف رقم المادة في الاستعلام ──
    # يدعم: "المادة 233", "مادة 233", "مادة رقم 233", "المادة رقم 85"
    art_pattern = re.compile(
        r'(?:المادة|مادة)\s*(?:رقم\s*)?(\d+)',
        re.UNICODE
    )
    art_match = art_pattern.search(query)
    art_num   = art_match.group(1) if art_match else None  # "233"

    if art_num:
        logger.info(f"استعلام مادة: رقم={art_num}")

    # ── توليد embedding الاستعلام ──
    try:
        query_embedding = embed_text(query)
    except Exception as e:
        logger.error(f"فشل embedding الاستعلام: {e}")
        return []

    all_matches = []
    seen_ids    = set()

    # ── بحث 1: فلترة مباشرة بالرقم إذا موجود ──
    if art_num:
        try:
            resp = index.query(
                vector=query_embedding,
                top_k=top_k * 3,
                include_metadata=True,
                filter={"art_nums": {"$in": [art_num]}}
            )
            for m in resp.get("matches", []):
                mid = m.get("id", "")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    all_matches.append(m)
            logger.info(f"فلترة $in [{art_num}]: {len(all_matches)} نتيجة")
        except Exception as e:
            logger.warning(f"فلترة Pinecone فشلت: {e}")

    # ── بحث 2: بحث دلالي عام ──
    try:
        resp2 = index.query(
            vector=query_embedding,
            top_k=top_k * 4,
            include_metadata=True
        )
        for m in resp2.get("matches", []):
            mid = m.get("id", "")
            if mid not in seen_ids:
                # إذا استعلام مادة: اقبل فقط ما يحتوي الرقم في metadata
                if art_num:
                    meta_nums = m.get("metadata", {}).get("art_nums", [])
                    meta_arts = m.get("metadata", {}).get("articles", "")
                    # فحص بالرقم الصافي في كلا الحقلين
                    if (art_num in meta_nums or
                        art_num in re.findall(r'\d+', meta_arts)):
                        seen_ids.add(mid)
                        all_matches.append(m)
                else:
                    seen_ids.add(mid)
                    all_matches.append(m)
    except Exception as e:
        logger.error(f"فشل البحث الدلالي: {e}")

    # ── fallback: إذا ما وجدنا شيء بالفلتر، خذ كل النتائج الدلالية ──
    if not all_matches:
        try:
            resp3 = index.query(
                vector=query_embedding,
                top_k=top_k * 4,
                include_metadata=True
            )
            all_matches = resp3.get("matches", [])
        except Exception as e:
            logger.error(f"فشل البحث الاحتياطي: {e}")
            return []

    # ── تحويل وتصفية ──
    min_score = 0.10 if art_num else 0.15
    raw = []
    for match in all_matches:
        meta  = match.get("metadata", {})
        score = round(match.get("score", 0), 3)
        if score < min_score:
            continue
        raw.append({
            "text":      meta.get("text", ""),
            "doc_title": meta.get("doc_title", "وثيقة"),
            "header":    meta.get("header", ""),
            "articles":  meta.get("articles", ""),
            "type":      meta.get("type", ""),
            "score":     score,
        })

    if not raw:
        logger.warning("لم يُعثر على نتائج")
        return []

    # ── تنويع النتائج ──
    sections = [c for c in raw if c["type"] == "section"]
    groups   = [c for c in raw if c["type"] == "group"]
    articles = [c for c in raw if c["type"] == "article"]
    others   = [c for c in raw if c["type"] not in ("section", "group", "article")]

    selected     = []
    seen_headers = set()

    def _add(candidates):
        for c in candidates:
            if len(selected) >= top_k:
                break
            key = (c["type"], c["header"][:60])
            if key not in seen_headers:
                seen_headers.add(key)
                selected.append(c)

    # لاستعلامات المواد: article أولاً
    if art_num:
        _add(articles)
        _add(groups)
        _add(sections)
    else:
        _add(sections)
        _add(groups)
        _add(articles)

    _add(others)
    _add([c for c in raw if c not in selected])

    logger.info(
        f"استُرجع {len(selected)} مقطع "
        f"(s={sum(1 for c in selected if c['type']=='section')}, "
        f"g={sum(1 for c in selected if c['type']=='group')}, "
        f"a={sum(1 for c in selected if c['type']=='article')})"
    )
    return selected[:top_k]