# ملخص شامل — Syrian Legal Advisor RAG System

## المشروع
Django + PostgreSQL + Pinecone — نظام استرجاع هجين (Hybrid RAG) للقوانين السورية بالعربية.

---

## الملفات الأساسية

| الملف | الوصف |
|-------|-------|
| `chatapp/rag_utils.py` | كل منطق RAG (استخراج، تحليل، بحث، تخزين) |
| `chatapp/views.py` | `_generate_ai_response` + `_extract_pdf_text` |
| `chatapp/models.py` | `LegalArticle`, `Document` |
| `requirements.txt` | يتضمن `pymupdf>=1.23.0` |

---

## البنية التقنية

### نموذج LegalArticle
```python
class LegalArticle(models.Model):
    doc                    = ForeignKey(Document)
    article_number         = PositiveIntegerField()        # رقم صحيح للبحث
    article_number_display = CharField(max_length=60)      # نص للعرض
    section_path           = CharField(max_length=500)
    text                   = TextField()
    order_in_doc           = IntegerField()
```

### ثوابت RAG (rag_utils.py)
```python
TOP_K      = 5
RRF_K      = 60
PG_WEIGHT  = 0.45
VEC_WEIGHT = 0.55
MIN_CHUNK_SIZE = 60
GROUP_SIZE = 3
```

---

## المشاكل التي حُلّت

### 1. استخراج PDF — 3 أنواع

**أ) Presentation Forms PDFs** (القانون التجاري وما شابهه)
- الحروف مخزّنة كـ Unicode Presentation Forms (U+FE70–U+FEFF)
- `is_presentation_form_pdf()` تكتشفه → `normalize_arabic_pdf()` تطبّق NFKC
- **الأفضلية: PyPDF2 دائماً** لهذا النوع (normalize_arabic_pdf بُنيت له)

**ب) Visual-order PDFs** (أرقام مقلوبة)
- الرقم `٠٠١` في الملف = المادة 100 (مخزّن بترتيب بصري معكوس)
- الصيغة: `-/٠٠١/المادة` أو `٠١المادة`
- الحل: `_fix_slash_art` و `_fix_inline_art` في `normalize_arabic_pdf` تعكس الأرقام

**ج) Custom Font PDFs** (القانون المدني — خط مخصص بدون ToUnicode map)
- PyPDF2 وpymupdf كلاهما يعطيان نصاً مشوّهاً (جودة ~0.25)
- الحالة الحالية: يُرفع كفقرات عادية لـ Pinecone بدون تحليل مواد
- **الحل المطلوب لاحقاً**: OCR بـ Tesseract — لم يُنفَّذ بعد

---

### 2. منطق اختيار مكتبة الاستخراج (`extract_pdf_text`)

```
pymupdf أولاً → يقيّم الجودة (_text_quality)
├── جودة ≥ 0.7  (Presentation Forms) → يشغّل PyPDF2 ويختاره دائماً
├── جودة < 0.4  (نص ضعيف)          → يشغّل PyPDF2 ويختار الأفضل
└── جودة متوسطة                       → pymupdf
```

**دالة `_text_quality`:**
- `pf_ratio > 0.08` → `0.75` (Presentation Forms — جيد)
- `diacrit > core_ar * 0.5` → `0.25` (خط مخصص — مشبوه)
- غير ذلك → `core_ar / total`

---

### 3. عدد المواد غير الصحيح

| المشكلة | السبب | الحل |
|---------|-------|------|
| 188 بدل 610 | أرقام مقلوبة + فاصل `ه` في الترويسات | `normalize_arabic_pdf` |
| 668 بدل 610 | مراجع داخلية "وفقاً للمادة 50" تُنشئ مواد وهمية | `_XREF` keyword set في `_parse_document` |
| 287 بدل 308 | شرط `len(prefix_before) > 4` أفرط في الحذف | استبدال بكلمات مفتاحية بدل الطول |
| 632 بدل 610 | مواد مكررة تُخزَّن برقم +1 | دمج النص بدل الزيادة (`seen_nums` dict) |

**مجموعة الكلمات المفتاحية للمراجع الداخلية:**
```python
_XREF = {'وفقاً','بموجب','المنصوص','المشار','المذكور','بأحكام',
         'لأحكام','نص','ونص','الواردة','المقررة','المبينة',
         'المحددة','المرقمة','المشمولة','المتعلقة'}
```

---

### 4. Law-aware Retrieval

**PostgreSQL:**
```python
if router.doc_ids:
    qs = qs.filter(doc_id__in=router.doc_ids)
```

**Pinecone:**
```python
_doc_flt = {"doc_id": {"$in": [str(d) for d in router.doc_ids]}}
# يُدمج مع فلتر أرقام المواد بـ $and
combined = {"$and": [_doc_flt, art_flt]}
```

**`_detect_doc_ids(query)`:** يقارن نص السؤال بعناوين الوثائق المفهرسة (≥ 4 أحرف).

---

### 5. Reranking + Confidence Scoring

في `search_similar_chunks` بعد RRF fusion:

```python
# Reranking: PostgreSQL exact matches → أعلى القائمة
if router.intent == QueryIntent.ARTICLE_EXACT:
    final.sort(key=_rerank_key)  # exact pg hits first

# Confidence
if exact_hit:                        confidence = "high"
elif score >= 0.008 or vec >= 0.55:  confidence = "high"
elif score >= 0.004 or vec >= 0.35:  confidence = "medium"
else:                                confidence = "low"
```

---

### 6. Duplicate Handling

**Pinecone:** MD5 hash dedup قبل الـ upsert داخل نفس الرفع.

**PostgreSQL (`_store_legal_articles`):**
```python
seen_nums: dict[int, int]  # num_int → index في to_create
# إذا تكرر الرقم: دمج النص
# إذا النص < 15 حرف: تجاهل (مرجع أو عنوان)
```

---

### 7. System Prompt (views.py)

```
أنت مستشار قانوني متخصص في القانون السوري.

قواعد صارمة:
1. اقتبس المادة كاملاً: "المادة [رقم] من [القانون]: [النص الكامل]"
2. لا معلومة خارج السياق المُقدَّم
3. عند سؤال برقم مادة: النص الكامل أولاً ثم شرح مبسط
4. عند سؤال موضوعي: أرقام المواد أولاً ثم ملخص كل منها
5. عند غياب المعلومة: "لا تتوفر هذه المعلومة في الوثائق المرفوعة حالياً"
6. أضف تنويه قانوني في نهاية كل إجابة
```

---

### 8. بناء السياق لـ GPT

```python
# كل chunk يُعرض هكذا:
f"【{i}】 {doc_title} | مواد: {articles} | ✓ دقيق\n{text}"
# confidence: "high" → "✓ دقيق" | "medium" → "~ متوسط" | "low" → "? ضعيف"
```

---

## حالة القوانين المرفوعة

| القانون | المواد المخزّنة | نوع الـ PDF | الحالة |
|---------|----------------|-------------|--------|
| القانون التجاري | ~610–632 | Presentation Forms | ✅ يعمل جيداً |
| قانون ثانٍ (308 م) | ~308 | Presentation Forms | ✅ يعمل جيداً |
| القانون المدني | 0 مادة | Custom Font | ⚠️ فقرات فقط في Pinecone |

---

## ما لم يُنفَّذ بعد

1. **OCR للقانون المدني** — Tesseract + Arabic language pack لـ custom font PDFs
2. **Cross-encoder reranking** — حالياً RRF فقط
3. **تصحيح ترتيب الأسطر** في visual-order PDFs (قيد PyPDF2)

---

## أوامر مفيدة

```bash
# تثبيت pymupdf (مطلوب على السيرفر)
pip install pymupdf --break-system-packages

# إعادة فهرسة وثيقة
POST /documents/{id}/reindex/

# حذف وثيقة (يحذف من Pinecone + PostgreSQL)
POST /documents/{id}/delete/
```

---

## تدفق رفع الوثيقة

```
PDF upload
  └─► _extract_pdf_text (views.py)
        └─► extract_pdf_text (rag_utils.py)
              ├─► _extract_with_pymupdf  → _text_quality
              ├─► _extract_with_pypdf2   → _text_quality
              └─► اختيار الأفضل
  └─► store_document_in_pinecone
        ├─► _store_pinecone
        │     └─► smart_chunk → clean_text → normalize_arabic_pdf
        │           └─► _build_hierarchical_chunks (section/group/article)
        └─► _store_legal_articles
              └─► _parse_document → LegalArticle.bulk_create
```

## تدفق البحث (RAG)

```
سؤال المستخدم
  └─► route_query → RouterResult (intent + art_nums + doc_ids)
  └─► structured_search (PostgreSQL ORM)   → pg_res
  └─► semantic_search (Pinecone)           → vec_res
  └─► _rrf_fuse (RRF fusion)
  └─► _diversify (section/group/article ordering)
  └─► reranking (exact pg hits first)
  └─► confidence scoring
  └─► _generate_ai_response (GPT)
```
