import json
import logging
import re
from typing import Dict, Any

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Avg, Count
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from datetime import timedelta

from openai import OpenAI
from PyPDF2 import PdfReader

from .models import (
    Document, UserProfile, LawyerProfile, Consultation,
    LawyerReview, Feedback, Message, LegalArticle,
    OfficialDocumentCategory, OfficialDocumentItem,
    GeneratedDocument, LegalDocumentType,
)
from .rag_utils import search_similar_chunks, store_document_in_pinecone
from .audio_utils import process_audio_file
from .maps_utils import get_coordinates, find_nearby_lawyers

logger = logging.getLogger(__name__)


# ==================== Helper Functions ====================

def is_admin(user):
    return user.is_staff or (hasattr(user, 'profile') and user.profile.user_type == 'admin')


def is_lawyer(user):
    """هل المستخدم محامٍ (بغض النظر عن التوثيق)"""
    return hasattr(user, 'lawyer_profile')

def is_verified_lawyer(user):
    """هل المحامي موثّق من الأدمن"""
    return hasattr(user, 'lawyer_profile') and user.lawyer_profile.is_verified


def smart_redirect(user):
    """إعادة توجيه ذكية حسب نوع المستخدم"""
    if is_admin(user):
        return redirect('admin_dashboard')
    elif is_lawyer(user):
        if user.lawyer_profile.is_verified:
            return redirect('lawyer_dashboard')
        else:
            return redirect('lawyer_pending')
    else:
        return redirect('index')


# ==================== Lawyer Login ====================

def lawyer_login(request):
    """صفحة تسجيل دخول المحامين المخصصة"""
    from django.contrib.auth import authenticate, login as auth_login
    if request.user.is_authenticated:
        return smart_redirect(request.user)

    error = False
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if not is_lawyer(user):
                error = 'not_lawyer'
            else:
                auth_login(request, user)
                return smart_redirect(user)
        else:
            error = True

    return render(request, 'chatapp/lawyer_login.html', {'error': error})


# ==================== Landing Page ====================

def landing(request):
    """صفحة الترحيب الرئيسية"""
    if request.user.is_authenticated:
        return smart_redirect(request.user)

    total_lawyers       = LawyerProfile.objects.filter(is_verified=True).count()
    total_consultations = Consultation.objects.count()
    total_users         = User.objects.filter(lawyer_profile__isnull=True).count()

    return render(request, 'chatapp/landing.html', {
        'total_lawyers':       total_lawyers,
        'total_consultations': total_consultations,
        'total_users':         total_users,
    })


# ==================== Authentication Views ====================

def register(request):
    """تسجيل مستخدم عادي جديد"""
    if request.user.is_authenticated:
        return redirect('index')

    email_error = None
    phone_error = None

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        email      = request.POST.get('email', '').strip()
        phone      = request.POST.get('phone', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()

        # التحقق من الإيميل
        if not email:
            email_error = "البريد الإلكتروني مطلوب."
        elif '@' not in email or '.' not in email.split('@')[-1]:
            email_error = "أدخل بريداً إلكترونياً صحيحاً."
        elif User.objects.filter(email=email).exists():
            email_error = "هذا البريد الإلكتروني مستخدم بالفعل."

        # التحقق من رقم الهاتف (اختياري لكن يجب أن يكون رقمياً إن أُدخل)
        if phone and not re.match(r'^\+?[\d\s\-]{7,20}$', phone):
            phone_error = "أدخل رقم هاتف صحيحاً."

        if form.is_valid() and not email_error and not phone_error:
            user = form.save(commit=False)
            user.email      = email
            user.first_name = first_name
            user.last_name  = last_name
            user.save()
            UserProfile.objects.create(user=user, user_type='user', phone=phone)
            login(request, user)
            return smart_redirect(user)
    else:
        form = UserCreationForm()

    return render(request, "register.html", {
        "form":        form,
        "email_error": email_error,
        "phone_error": phone_error,
    })


def lawyer_register(request):
    """تسجيل محامي جديد"""
    if request.user.is_authenticated:
        return redirect('index')

    email_error = None

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        email      = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()

        # التحقق من الإيميل
        if not email:
            email_error = "البريد الإلكتروني مطلوب."
        elif '@' not in email or '.' not in email.split('@')[-1]:
            email_error = "أدخل بريداً إلكترونياً صحيحاً."
        elif User.objects.filter(email=email).exists():
            email_error = "هذا البريد الإلكتروني مستخدم بالفعل."

        if form.is_valid() and not email_error:
            user = form.save(commit=False)
            user.first_name = first_name
            user.last_name  = last_name
            user.email      = email
            user.save()

            UserProfile.objects.create(user=user, user_type='lawyer')

            latitude  = request.POST.get('latitude')
            longitude = request.POST.get('longitude')
            lat = lng = None
            if latitude and longitude:
                try:
                    lat = float(latitude)
                    lng = float(longitude)
                except (ValueError, TypeError):
                    lat = lng = None

            if lat is None or lng is None:
                address = request.POST.get('office_address', '').strip()
                if address:
                    try:
                        lat, lng = get_coordinates(address)
                    except Exception as e:
                        logger.error(f"فشل الإحداثيات عند التسجيل: {e}")

            exp = request.POST.get('experience_years', '0')
            try:
                exp = int(exp)
            except (ValueError, TypeError):
                exp = 0

            LawyerProfile.objects.create(
                user=user,
                license_number=request.POST.get('license_number', ''),
                specialization=request.POST.get('specialization', 'civil'),
                experience_years=exp,
                office_name=request.POST.get('office_name', ''),
                office_address=request.POST.get('office_address', ''),
                office_phone=request.POST.get('office_phone', ''),
                mobile_phone=request.POST.get('mobile_phone', ''),
                office_email=request.POST.get('office_email', user.email),
                description=request.POST.get('description', ''),
                latitude=lat,
                longitude=lng,
                is_verified=False,
            )
            # لا نعمل login — ننتظر موافقة الأدمن
            return redirect('lawyer_pending')
    else:
        form = UserCreationForm()

    return render(request, "chatapp/lawyer_register.html", {
        "form":             form,
        "email_error":      email_error,
        "specializations":  LawyerProfile.SPECIALIZATIONS,
        "MAPTILER_API_KEY": settings.MAPTILER_API_KEY,
    })


# ==================== Main Pages ====================

@login_required
def index(request):
    doc_categories = (
        OfficialDocumentCategory.objects
        .filter(is_active=True)
        .prefetch_related('items')
    )
    context = {
        'total_lawyers':       LawyerProfile.objects.filter(is_verified=True).count(),
        'total_consultations': Consultation.objects.count(),
        'total_users':         User.objects.filter(lawyer_profile__isnull=True, is_staff=False).count(),
        'user_consultations':  Consultation.objects.filter(user=request.user).count(),
        'is_lawyer':           is_lawyer(request.user),
        'is_admin':            is_admin(request.user),
        'doc_categories':      doc_categories,
    }
    return render(request, "chatapp/index.html", context)


def legal_documents(request):
    """منشئ الوثائق القانونية — متاح للجميع"""
    saved_docs = []
    if request.user.is_authenticated:
        saved_docs = list(
            GeneratedDocument.objects
            .filter(user=request.user)
            .values('id', 'doc_type', 'title', 'created_at')
            .order_by('-created_at')[:30]
        )
        for d in saved_docs:
            d['created_at'] = d['created_at'].strftime('%Y-%m-%d')

    # الأنواع المفعّلة — من قاعدة البيانات إن وُجدت وإلا من الافتراضي
    active_types_qs = LegalDocumentType.objects.filter(is_active=True).order_by('order', 'name')
    active_types = list(active_types_qs.values('slug', 'name', 'icon', 'description')) if active_types_qs.exists() else []

    return render(request, 'chatapp/legal_documents.html', {
        'saved_docs_json':  json.dumps(saved_docs, ensure_ascii=False),
        'active_types_json': json.dumps(active_types, ensure_ascii=False),
    })


@login_required
@require_POST
def save_generated_document(request):
    """حفظ وثيقة منشأة في قاعدة البيانات"""
    try:
        data = json.loads(request.body)
        doc_type     = data.get('doc_type', '').strip()
        title        = data.get('title', '').strip()
        html_content = data.get('html_content', '').strip()
        form_data    = data.get('form_data', {})
        if not doc_type or not html_content:
            return JsonResponse({'error': 'بيانات ناقصة'}, status=400)
        doc = GeneratedDocument.objects.create(
            user=request.user,
            doc_type=doc_type,
            title=title or doc_type,
            html_content=html_content,
            form_data=form_data,
        )
        return JsonResponse({
            'success': True,
            'id': doc.id,
            'created_at': doc.created_at.strftime('%Y-%m-%d'),
            'message': 'تم حفظ الوثيقة بنجاح',
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def load_generated_document(request, doc_id):
    """تحميل وثيقة محفوظة"""
    doc = get_object_or_404(GeneratedDocument, id=doc_id, user=request.user)
    return JsonResponse({
        'id': doc.id,
        'doc_type': doc.doc_type,
        'title': doc.title,
        'html_content': doc.html_content,
        'form_data': doc.form_data,
        'created_at': doc.created_at.strftime('%Y-%m-%d'),
    })


@login_required
@require_POST
def delete_generated_document(request, doc_id):
    """حذف وثيقة محفوظة"""
    doc = get_object_or_404(GeneratedDocument, id=doc_id, user=request.user)
    doc.delete()
    return JsonResponse({'success': True})


@login_required
def official_documents(request):
    """صفحة الأوراق الرسمية — عرض فقط للمستخدمين والمحامين"""
    doc_categories = (
        OfficialDocumentCategory.objects
        .filter(is_active=True)
        .prefetch_related('items')
    )
    return render(request, 'chatapp/official_documents.html', {
        'doc_categories': doc_categories,
        'is_lawyer':      is_lawyer(request.user),
        'is_admin':       is_admin(request.user),
    })


@login_required
def chat(request):
    docs = Document.objects.order_by("-uploaded_at")
    return render(request, "chatapp/chat.html", {"docs": docs})


@login_required
def chat_new(request):
    return render(request, "chatapp/chat_new.html", {
        'is_lawyer': is_lawyer(request.user),
        'is_admin': is_admin(request.user),
    })


# ==================== Document Management ====================

@login_required
@require_POST
def upload_document(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("هذه العملية للمدير فقط")

    file  = request.FILES.get("file")
    title = request.POST.get("title") or getattr(file, "name", "وثيقة بدون عنوان")
    if not file:
        return HttpResponseBadRequest("لم يتم رفع أي ملف.")

    doc = Document.objects.create(title=title, file=file, uploaded_by=request.user)

    result = {
        'success':        False,
        'doc_id':         doc.id,
        'title':          doc.title,
        'text_len':       0,
        'chunks_stored':  0,
        'articles_count': 0,
        'error':          None,
        'stage':          'created',
    }

    try:
        # المرحلة 1: استخراج النص
        result['stage'] = 'extracting'
        extracted_text = _extract_text_from_document(doc)
        doc.extracted_text = extracted_text
        doc.save()
        result['text_len'] = len(extracted_text)

        if not extracted_text.strip():
            result['error'] = 'النص فارغ — تأكد أن الـ PDF يحتوي نصاً وليس صوراً فقط'
            logger.warning(f"الوثيقة #{doc.id}: {result['error']}")
        else:
            # المرحلة 2: الفهرسة في Pinecone + LegalArticle
            result['stage'] = 'indexing'
            # store_document_in_pinecone يخزّن في Pinecone + LegalArticle تلقائياً
            chunks_stored = store_document_in_pinecone(
                doc.id, extracted_text, doc_title=doc.title
            )
            result['chunks_stored'] = chunks_stored
            # قراءة عدد المواد
            result['articles_count'] = LegalArticle.objects.filter(doc_id=doc.id).count()

            if chunks_stored == 0 and result['articles_count'] == 0:
                result['error'] = 'فشل التخزين في Pinecone و LegalArticle — تحقق من مفاتيح API'
            else:
                result['success'] = True
                logger.info(f"الوثيقة #{doc.id} '{doc.title}': "
                            f"{chunks_stored} مقطع Pinecone | "
                            f"{result['articles_count']} مادة قانونية")

    except Exception as e:
        result['error'] = f"خطأ في مرحلة {result['stage']}: {str(e)}"
        logger.error(f"فشل معالجة الوثيقة {doc.id}: {e}", exc_info=True)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse(result)

    # للـ form العادي: أضف message واعمل redirect
    if result['success']:
        from django.contrib import messages
        messages.success(request,
            f"✅ '{doc.title}' رُفعت وفُهرست — "
            f"{result['chunks_stored']} مقطع Pinecone | "
            f"{result['articles_count']} مادة قانونية")
    else:
        from django.contrib import messages
        messages.error(request, f"⚠️ '{doc.title}' رُفعت لكن فشلت الفهرسة: {result['error']}")

    return redirect("admin_documents")


@login_required
@require_POST
def delete_document(request, doc_id):
    """حذف وثيقة — DB + Pinecone + LegalArticle"""
    if not is_admin(request.user):
        return HttpResponseForbidden()
    doc = get_object_or_404(Document, id=doc_id)

    # 1. حذف vectors من Pinecone
    try:
        from .rag_utils import index as pinecone_index
        pinecone_index.delete(filter={"doc_id": str(doc_id)})
        logger.info(f"Pinecone: حُذفت vectors الوثيقة #{doc_id}")
    except Exception as e:
        logger.warning(f"Pinecone delete failed #{doc_id}: {e}")

    # 2. حذف المواد من LegalArticle (CASCADE يكفي لكن نُصرّح للوضوح)
    try:
        n, _ = LegalArticle.objects.filter(doc_id=doc_id).delete()
        logger.info(f"LegalArticle: حُذفت {n} مادة للوثيقة #{doc_id}")
    except Exception as e:
        logger.warning(f"LegalArticle delete failed #{doc_id}: {e}")

    doc.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def reindex_document(request, doc_id):
    """إعادة فهرسة — Pinecone + LegalArticle (للمدير)"""
    if not is_admin(request.user):
        return HttpResponseForbidden()
    doc = get_object_or_404(Document, id=doc_id)

    try:
        # إعادة استخراج النص
        extracted_text = _extract_text_from_document(doc)
        if not extracted_text.strip():
            return JsonResponse({'success': False, 'error': 'النص فارغ بعد الاستخراج'})

        doc.extracted_text = extracted_text
        doc.save()

        # حذف Pinecone القديم
        try:
            from .rag_utils import index as pinecone_index
            pinecone_index.delete(filter={"doc_id": str(doc_id)})
        except Exception as e:
            logger.warning(f"فشل حذف vectors قديمة: {e}")

        # فهرسة جديدة (Pinecone + LegalArticle في استدعاء واحد)
        chunks_stored = store_document_in_pinecone(
            doc.id, extracted_text, doc_title=doc.title
        )
        
        # قراءة عدد المواد المخزّنة
        articles_count = LegalArticle.objects.filter(doc_id=doc_id).count()

        return JsonResponse({
            'success':        True,
            'chunks':         chunks_stored,
            'articles_count': articles_count,
            'text_len':       len(extracted_text),
        })
    except Exception as e:
        logger.error(f"reindex failed #{doc_id}: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


def _extract_text_from_document(doc):
    try:
        file_path = doc.file.path
        file_ext = file_path.lower().split('.')[-1]
        if file_ext == "pdf":
            return _extract_pdf_text(file_path)
        else:
            with open(file_path, "rb") as f:
                return f.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"فشل استخراج النص: {e}")
        return ""


def _extract_pdf_text(pdf_path):
    """يستخدم rag_utils.extract_pdf_text الذي يجرب pymupdf أولاً ثم PyPDF2."""
    try:
        from .rag_utils import extract_pdf_text as _rag_extract
        return _rag_extract(pdf_path)
    except Exception as e:
        logger.error(f"فشل استخراج PDF: {e}")
        # fallback مباشر
        try:
            reader = PdfReader(pdf_path)
            return "\n".join([p.extract_text() or "" for p in reader.pages])
        except Exception as e2:
            logger.error(f"فشل PyPDF2 الاحتياطي: {e2}")
            return ""


# ==================== Chat with RAG ====================

@login_required
@require_POST
def chat_send(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON غير صالح")

    user_message = payload.get("question", "").strip()
    if not user_message:
        return HttpResponseBadRequest("رسالة فارغة")

    # نطلب أكثر من RAG_TOP_K ثم نصفي الضعيفة داخل _generate_ai_response
    top_k = max(getattr(settings, 'RAG_TOP_K_RESULTS', 3), 5)
    try:
        retrieved_chunks = search_similar_chunks(user_message, top_k=top_k)
    except Exception as e:
        logger.error(f"فشل بحث RAG: {e}")
        retrieved_chunks = []

    try:
        ai_response = _generate_ai_response(user_message, retrieved_chunks)
    except Exception as e:
        logger.error(f"فشل توليد الذكاء الاصطناعي: {e}")
        return JsonResponse({"error": "فشل إنشاء الاستجابة."}, status=500)

    # نُعيد النص فقط للواجهة (للعرض وعدد المصادر)
    chunk_texts = [
        c["text"] if isinstance(c, dict) else c
        for c in retrieved_chunks
    ]
    return JsonResponse({"reply": ai_response, "retrieved_chunks": chunk_texts})


def _generate_ai_response(question: str, context_chunks: list) -> str:
    """
    يولّد رداً من GPT مبنياً على المقاطع المسترجعة.
    يقبل context_chunks إما قائمة dicts (من rag_utils الجديد)
    أو قائمة strings (للتوافق مع الإصدار القديم).
    """
    oai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

    # ── بناء السياق المنسّق ──
    if context_chunks:
        context_parts = []
        for i, chunk in enumerate(context_chunks, 1):
            if isinstance(chunk, dict):
                title      = chunk.get("doc_title", "وثيقة")
                header     = chunk.get("header", "")
                text       = chunk.get("text", "").strip()
                confidence = chunk.get("confidence", "")
                articles   = chunk.get("articles", "")
                conf_label = {"high": "✓ دقيق", "medium": "~ متوسط", "low": "? ضعيف"}.get(confidence, "")
                meta_parts = [title]
                if articles: meta_parts.append(f"مواد: {articles}")
                if conf_label: meta_parts.append(conf_label)
                label = " | ".join(meta_parts)
                context_parts.append(f"【{i}】 {label}\n{text}")
            else:
                context_parts.append(f"【{i}】\n{chunk}")
        context_text = "\n\n---\n\n".join(context_parts)
        has_context  = True
    else:
        context_text = ""
        has_context  = False

    # ── System Prompt ──
    system_prompt = """\
أنت مستشار قانوني متخصص في القانون السوري. مهمتك الإجابة بشكل شامل ودقيق ومفهوم بناءً حصراً على مقاطع الوثائق المُقدَّمة في السياق.

---

 أولاً — قواعد الاقتباس والمصادر (إلزامية في كل إجابة):

- **اقتبس نص المادة كاملاً حرفياً** دون حذف أو اختصار.
- **صيغة الاقتباس الموحدة**:
   **المادة [رقم] من [اسم القانون كاملاً]:** [النص الكامل للمادة]
- بعد كل اقتباس، اذكر المصدر بوضوح:
   📌 **المصدر:** [اسم القانون] — المادة [رقم]
- إذا تعددت المواد، رقّم كل مادة واذكر مصدرها بشكل منفصل.

---

 ثانياً — طريقة الإجابة حسب نوع السؤال:

 🔹 النوع 1: سؤال عن مادة بالرقم (مثال: "ما نص المادة 50؟")
1. **النص الكامل** للمادة (اقتبسه حرفياً).
2. **الشرح التطبيقي**: ماذا تعني هذه المادة عملياً؟ وضّح بلغة بسيطة.
3. **تطبيق على حالة المستخدم**: إذا ذكر المستخدم وضعاً أو قضية، اشرح كيف تنطبق هذه المادة على حالته تحديداً.
4. **مثال توضيحي بسيط**: اضرب مثالاً واقعياً قصيراً يوضّح تطبيق المادة.
   > 💡 **مثال:** [مثال عملي قصير]
5. 📌 المصدر.

---

 🔹 النوع 2: سؤال موضوعي (مثال: "ما شروط صحة العقد؟" أو "ما حقوق العامل؟")
1. **مقدمة موجزة** (جملة واحدة): ما الذي تنظّمه هذه المواد.
2. **عرض المواد ذات الصلة** بالترتيب، لكل مادة:
   - نصها الكامل مع المصدر
   - شرح مختصر لما تعنيه
3. **الخلاصة التطبيقية**: ربط المواد بسؤال المستخدم — ماذا يعني هذا في حالته؟
4. **مثال توضيحي بسيط** يجمع أثر هذه المواد معاً.
   > 💡 **مثال:** [مثال عملي قصير]

---

 🔹 النوع 3: سؤال إجرائي (مثال: "كيف أرفع دعوى؟" أو "ما الخطوات القانونية؟")
1. اذكر المواد القانونية المنظِّمة للإجراء مع نصها ومصدرها.
2. اشرح الخطوات الإجرائية المستنبطة من هذه المواد بشكل مرقّم.
3. طبّق الخطوات على وضع المستخدم إذا ذكر تفاصيل.
4. مثال توضيحي.

---

 🔹 النوع 4: سؤال مقارن أو "هل يجوز؟" (مثال: "هل يجوز فسخ العقد شفهياً؟")
1. اذكر المواد التي تعالج الموضوع مع نصها ومصدرها.
2. أجب بـ **نعم / لا / يتوقف على شرط** مع التعليل القانوني المستنبط من النص.
3. اشرح الاستثناءات إن وُجدت.
4. طبّق على حالة المستخدم.
5. مثال توضيحي.

---

 ثالثاً — قواعد عامة إلزامية:

- **لا تُضف أي معلومة** غير موجودة في المقاطع المُقدَّمة، حتى لو كنت تعرفها.
- **عند غياب المعلومة كلياً**: قل: "لا تتوفر هذه المعلومة في الوثائق المرفوعة حالياً."
- **عند غياب جزئي**: اذكر ما هو متوفر ونوّه بأن الإجابة الكاملة تستلزم مراجعة الوثيقة المختصة.
- لا تخمّن ولا تجتهد خارج النص.

---

 رابعاً — التنبيه القانوني (يُضاف دائماً في النهاية):

⚠️ المعلومات أعلاه مستخرجة من الوثائق القانونية المرفوعة ولا تُغني عن استشارة محامٍ مختص.
"""

    # ── رسالة المستخدم مع السياق ──
    if has_context:
        user_content = (
            f"السؤال: {question}\n\n"
            f"=== مقاطع الوثائق المرتبطة ===\n\n{context_text}"
        )
    else:
        user_content = (
            f"السؤال: {question}\n\n"
            "[لم يُعثر على وثائق مرتبطة بهذا السؤال في قاعدة البيانات.]"
        )

    response = oai_client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        max_tokens=settings.OPENAI_MAX_TOKENS,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


# ==================== Lawyers Directory ====================

@login_required
def lawyers_list(request):
    specialization = request.GET.get('specialization', '')
    city = request.GET.get('city', '')
    search_query = request.GET.get('q', '')

    lawyers = LawyerProfile.objects.filter(is_verified=True, is_available=True).select_related('user')

    # إخفاء المحامي المسجّل من الدليل
    if request.user.is_authenticated and is_lawyer(request.user):
        lawyers = lawyers.exclude(user=request.user)

    if specialization:
        lawyers = lawyers.filter(specialization=specialization)
    if city:
        lawyers = lawyers.filter(office_address__icontains=city)
    if search_query:
        lawyers = lawyers.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(office_name__icontains=search_query)
        )

    sort_by = request.GET.get('sort', 'rating')
    if sort_by == 'experience':
        lawyers = lawyers.order_by('-experience_years')
    elif sort_by == 'price_low':
        lawyers = lawyers.order_by('consultation_fee')
    elif sort_by == 'price_high':
        lawyers = lawyers.order_by('-consultation_fee')
    else:
        lawyers = lawyers.order_by('-rating', '-total_reviews')

    user_lat = request.GET.get('lat')
    user_lng = request.GET.get('lng')

    if user_lat and user_lng:
        try:
            nearby = find_nearby_lawyers(float(user_lat), float(user_lng), max_distance_km=50)
            return render(request, 'chatapp/lawyers_list.html', {
                'lawyers_with_distance': nearby,
                'lawyers_count':         len(nearby),
                'specializations':       LawyerProfile.SPECIALIZATIONS,
                'MAPTILER_API_KEY':      settings.MAPTILER_API_KEY,
            })
        except Exception as e:
            logger.error(f"فشل البحث الجغرافي: {e}")

    paginator  = Paginator(lawyers, 12)
    page_obj   = paginator.get_page(request.GET.get('page', 1))
    context = {
        'lawyers':        page_obj,
        'lawyers_count':  lawyers.count(),
        'specializations': LawyerProfile.SPECIALIZATIONS,
        'MAPTILER_API_KEY': settings.MAPTILER_API_KEY,
    }
    return render(request, 'chatapp/lawyers_list.html', context)


@login_required
def lawyers_map(request):
    """صفحة خريطة المحامين — MapTiler"""
    lawyers = LawyerProfile.objects.filter(
        is_verified=True, is_available=True,
        latitude__isnull=False, longitude__isnull=False
    ).select_related('user')

    # إخفاء المحامي المسجّل من الخريطة
    if request.user.is_authenticated and is_lawyer(request.user):
        lawyers = lawyers.exclude(user=request.user)

    lawyers_data = [
        {
            'id':                  l.id,
            'name':                l.user.get_full_name() or l.user.username,
            'specialization':      l.get_specialization_display(),
            'specialization_code': l.specialization,
            'rating':              float(l.rating),
            'reviews':             l.total_reviews,
            'experience':          l.experience_years,
            'lat':                 float(l.latitude),
            'lng':                 float(l.longitude),
            'address':             l.office_address or '',
            'phone':               l.office_phone or '',
            'fee':                 float(l.consultation_fee),
        }
        for l in lawyers
    ]

    return render(request, 'chatapp/lawyers_map.html', {
        'lawyers_json':     json.dumps(lawyers_data, ensure_ascii=False),
        'MAPTILER_API_KEY': settings.MAPTILER_API_KEY,
        'specializations':  LawyerProfile.SPECIALIZATIONS,
    })


def lawyer_detail(request, lawyer_id):
    lawyer = get_object_or_404(LawyerProfile.objects.select_related('user'), id=lawyer_id, is_verified=True)
    reviews = lawyer.reviews.select_related('user').order_by('-created_at')[:10]
    rating_distribution = {i: lawyer.reviews.filter(rating=i).count() for i in range(1, 6)}

    can_review = (
        request.user.is_authenticated and
        not LawyerReview.objects.filter(lawyer=lawyer, user=request.user).exists()
    )

    already_consulted = (
        request.user.is_authenticated and
        Consultation.objects.filter(user=request.user, lawyer=lawyer.user).exists()
    )

    return render(request, 'chatapp/lawyer_detail.html', {
        'lawyer': lawyer,
        'reviews': reviews,
        'rating_distribution': rating_distribution,
        'can_review': can_review,
        'already_consulted': already_consulted,
        'MAPTILER_API_KEY': settings.MAPTILER_API_KEY,
    })


@login_required
@require_POST
def submit_lawyer_review(request, lawyer_id):
    lawyer = get_object_or_404(LawyerProfile, id=lawyer_id)
    if LawyerReview.objects.filter(lawyer=lawyer, user=request.user).exists():
        return JsonResponse({'error': 'لقد قيّمت هذا المحامي من قبل'}, status=400)

    try:
        rating = int(request.POST.get('rating'))
        if not (1 <= rating <= 5):
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({'error': 'تقييم غير صالح'}, status=400)

    LawyerReview.objects.create(lawyer=lawyer, user=request.user, rating=rating, comment=request.POST.get('comment', ''))
    lawyer.refresh_from_db()
    u = request.user
    full_name = u.get_full_name() or u.username
    initial   = (u.first_name[:1] or u.username[:1]).upper()
    return JsonResponse({
        'success': True,
        'new_rating': float(lawyer.rating),
        'total_reviews': lawyer.total_reviews,
        'user_name': full_name,
        'user_initial': initial,
    })


# ==================== Consultations ====================

from django.core.mail import send_mail
from django.urls import reverse

@login_required
def request_consultation(request, lawyer_id):
    lawyer_profile = get_object_or_404(LawyerProfile, id=lawyer_id, is_verified=True)

    if request.method == 'GET':
        return render(request, 'chatapp/consultation_chat.html', {
            'lawyer_profile': lawyer_profile,
        })

    # POST — create consultation
    audio_file = request.FILES.get('audio_file')

    # منع الإرسال المتعدد لنفس المحامي
    if Consultation.objects.filter(user=request.user, lawyer=lawyer_profile.user).exists():
        return JsonResponse({'error': 'لقد أرسلت طلب استشارة لهذا المحامي مسبقاً'}, status=400)

    # الرسالة الثابتة
    title       = 'طلب استشارة قانونية'
    description = 'مرحباً, أريد استشارتك بقضية معينة.'

    consultation = Consultation.objects.create(
        user=request.user,
        lawyer=lawyer_profile.user,
        title=title,
        description=description,
        audio_file=audio_file if audio_file else None
    )

    if audio_file:
        try:
            consultation.audio_transcription = process_audio_file(audio_file, use_whisper=True)
            consultation.save()
        except Exception as e:
            logger.error(f"فشل تحويل الصوت: {e}")

    # ========== EMAIL 1: Send Notification to Lawyer ==========
    try:
        lawyer_email = lawyer_profile.user.email
        lawyer_name = lawyer_profile.user.get_full_name() or lawyer_profile.user.username
        user_name = request.user.get_full_name() or request.user.username
        
        consultation_url = request.build_absolute_uri(
            reverse('consultation_detail', args=[consultation.id])
        )
        dashboard_url = request.build_absolute_uri(
            reverse('lawyer_consultations')
        )
        
        subject = f"📋 استشارة جديدة من {user_name} - {title}"
        
        html_message = f"""
        <html dir="rtl">
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px; }}
                .header {{ background: linear-gradient(135deg, #0b1628, #b8965a); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 20px; }}
                .info-box {{ background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 15px 0; }}
                .button {{ display: inline-block; background: #b8965a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
                .footer {{ font-size: 12px; color: #666; text-align: center; margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>📋 استشارة قانونية جديدة</h2>
                </div>
                <div class="content">
                    <p>السلام عليكم، <strong>{lawyer_name}</strong></p>
                    <p>يوجد استشارة قانونية جديدة مطلوبة من <strong>{user_name}</strong>.</p>
                    
                    <div class="info-box">
                        <h3>تفاصيل الاستشارة:</h3>
                        <p><strong>📌 العنوان:</strong> {title}</p>
                        <p><strong>📝 الوصف:</strong></p>
                        <p>{description[:500]}{'...' if len(description) > 500 else ''}</p>
                        <p><strong>👤 مقدم الطلب:</strong> {user_name}</p>
                        <p><strong>📅 التاريخ:</strong> {consultation.created_at.strftime('%Y-%m-%d %H:%M')}</p>
                    </div>
                    
                    <p>للاطلاع على التفاصيل الكاملة والرد على الاستشارة:</p>
                    <p style="text-align: center;">
                        <a href="{consultation_url}" class="button">📖 عرض الاستشارة</a>
                    </p>
                    <p style="text-align: center;">
                        <a href="{dashboard_url}">📊 الذهاب إلى لوحة التحكم</a>
                    </p>
                    
                    <p><strong>ملاحظة:</strong> يُرجى تسجيل الدخول إلى حسابك للرد على هذه الاستشارة.</p>
                </div>
                <div class="footer">
                    <p>هذا البريد تلقائي، يرجى عدم الرد عليه.</p>
                    <p>© المستشار القانوني السوري</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
مرحباً {lawyer_name}

لديك استشارة قانونية جديدة من {user_name}.

تفاصيل الاستشارة:
العنوان: {title}
الوصف: {description}
التاريخ: {consultation.created_at.strftime('%Y-%m-%d %H:%M')}

لعرض الاستشارة والرد عليها:
{consultation_url}

أو قم بزيارة لوحة التحكم:
{dashboard_url}

مع تحيات,
المستشار القانوني السوري
"""
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[lawyer_email],
            fail_silently=False,
            html_message=html_message,
        )
        
        logger.info(f"تم إرسال إشعار البريد الإلكتروني إلى المحامي {lawyer_email} للاستشارة #{consultation.id}")
        
    except Exception as e:
        logger.error(f"فشل إرسال البريد الإلكتروني إلى المحامي: {e}")

    # ========== EMAIL 2: Send Confirmation to User (STEP 2) ==========
    try:
        user_email = request.user.email
        user_name = request.user.get_full_name() or request.user.username
        lawyer_name = lawyer_profile.user.get_full_name() or lawyer_profile.user.username
        
        user_consultations_url = request.build_absolute_uri(
            reverse('my_consultations')
        )
        
        user_subject = f"✅ تم إرسال استشارتك إلى المحامي - {title}"
        
        user_html_message = f"""
        <html dir="rtl">
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px; }}
                .header {{ background: linear-gradient(135deg, #0b1628, #b8965a); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 20px; }}
                .info-box {{ background: #e8f5e9; padding: 15px; border-radius: 8px; margin: 15px 0; }}
                .button {{ display: inline-block; background: #b8965a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
                .footer {{ font-size: 12px; color: #666; text-align: center; margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>✅ تم إرسال استشارتك بنجاح</h2>
                </div>
                <div class="content">
                    <p>عزيزي <strong>{user_name}</strong>،</p>
                    <p>تم إرسال استشارتك "<strong>{title}</strong>" إلى المحامي <strong>{lawyer_name}</strong>.</p>
                    
                    <div class="info-box">
                        <h3>📋 ملخص الاستشارة:</h3>
                        <p><strong>العنوان:</strong> {title}</p>
                        <p><strong>الوصف:</strong> {description[:200]}{'...' if len(description) > 200 else ''}</p>
                        <p><strong>تاريخ الإرسال:</strong> {consultation.created_at.strftime('%Y-%m-%d %H:%M')}</p>
                        <p><strong>الحالة:</strong> قيد الانتظار</p>
                    </div>
                    
                    <p>سيتم إعلامك عندما يرد المحامي على استشارتك.</p>
                    
                    <p style="text-align: center;">
                        <a href="{user_consultations_url}" class="button">📋 متابعة استشاراتي</a>
                    </p>
                    
                    <p>يمكنك متابعة حالة استشاراتك من خلال لوحة التحكم.</p>
                </div>
                <div class="footer">
                    <p>هذا بريد تلقائي، يرجى عدم الرد عليه.</p>
                    <p>© المستشار القانوني السوري</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        user_plain_message = f"""
عزيزي {user_name}

تم إرسال استشارتك "{title}" إلى المحامي {lawyer_name}.

تفاصيل الاستشارة:
العنوان: {title}
الوصف: {description}
التاريخ: {consultation.created_at.strftime('%Y-%m-%d %H:%M')}
الحالة: قيد الانتظار

سيتم إعلامك عندما يرد المحامي على استشارتك.

لمتابعة استشاراتك:
{user_consultations_url}

مع تحيات,
المستشار القانوني السوري
"""
        
        send_mail(
            subject=user_subject,
            message=user_plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            fail_silently=False,
            html_message=user_html_message,
        )
        
        logger.info(f"تم إرسال البريد الإلكتروني للمستخدم {user_email} تأكيداً للاستشارة #{consultation.id}")
        
    except Exception as e:
        logger.error(f"فشل إرسال البريد الإلكتروني للمستخدم: {e}")

    return JsonResponse({'success': True, 'consultation_id': consultation.id, 'message': 'تم إرسال الطلب بنجاح'})

@login_required
def my_consultations(request):
    qs = request.user.consultations.select_related('lawyer').order_by('-created_at')
    paginator = Paginator(qs, 10)
    return render(request, 'chatapp/consultations_list.html', {
        'consultations':   paginator.get_page(request.GET.get('page', 1)),
        'pending_count':   qs.filter(status='pending').count(),
        'accepted_count':  qs.filter(status='accepted').count(),
        'title': 'استشاراتي',
    })


@login_required
def consultation_detail(request, consultation_id):
    consultation = get_object_or_404(Consultation.objects.select_related('user', 'lawyer'), id=consultation_id)
    if consultation.user != request.user and consultation.lawyer != request.user:
        return HttpResponseForbidden()
    return render(request, 'chatapp/consultation_detail.html', {'consultation': consultation})


# ==================== Feedback System ====================

@login_required
def submit_feedback(request):
    if request.method == 'POST':
        subject = request.POST.get('subject', '')
        message = request.POST.get('message', '')
        audio_file = request.FILES.get('audio_file')

        if not subject or not message:
            return JsonResponse({'error': 'الرجاء ملء جميع الحقول'}, status=400)

        feedback = Feedback.objects.create(
            user=request.user,
            feedback_type=request.POST.get('feedback_type', 'suggestion'),
            subject=subject, message=message,
            audio_file=audio_file if audio_file else None
        )

        if audio_file:
            try:
                feedback.audio_transcription = process_audio_file(audio_file, use_whisper=True)
                feedback.save()
            except Exception as e:
                logger.error(f"فشل تحويل الصوت: {e}")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'تم إرسال ملاحظتك بنجاح!'})
        return redirect('index')

    return render(request, 'chatapp/feedback_form.html', {'feedback_types': Feedback.FEEDBACK_TYPES})


# ==================== Lawyer Dashboard ====================

def lawyer_verified_required(view_func):
    """ديكوريتور: يتطلب محامٍ موثّق"""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not is_lawyer(request.user):
            return redirect('index')
        if not request.user.lawyer_profile.is_verified:
            return redirect('lawyer_pending')
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@user_passes_test(is_lawyer)
def lawyer_my_public_profile(request):
    """عرض ملف المحامي العام داخل لوحة التحكم"""
    lawyer = get_object_or_404(LawyerProfile, user=request.user)
    reviews = lawyer.reviews.select_related('user').order_by('-created_at')[:10]
    rating_distribution = {i: lawyer.reviews.filter(rating=i).count() for i in range(1, 6)}
    return render(request, 'chatapp/lawyer_public_profile.html', {
        'lawyer': lawyer,
        'reviews': reviews,
        'rating_distribution': rating_distribution,
        'MAPTILER_API_KEY': settings.MAPTILER_API_KEY,
    })


@login_required
@user_passes_test(is_lawyer)
def lawyer_dashboard(request):
    lawyer_profile = request.user.lawyer_profile
    stats = {
        'total_consultations': request.user.lawyer_consultations.count(),
        'pending_consultations': request.user.lawyer_consultations.filter(status='pending').count(),
        'accepted_consultations': request.user.lawyer_consultations.filter(status='accepted').count(),
        'completed_consultations': request.user.lawyer_consultations.filter(status='completed').count(),
        'total_reviews': lawyer_profile.total_reviews,
        'average_rating': lawyer_profile.rating,
    }
    return render(request, 'chatapp/lawyer_dashboard.html', {
        'lawyer_profile': lawyer_profile,
        'stats': stats,
        'recent_consultations': request.user.lawyer_consultations.select_related('user').order_by('-created_at')[:5],
        'recent_reviews': lawyer_profile.reviews.select_related('user').order_by('-created_at')[:5],
    })


@login_required
@user_passes_test(is_lawyer)
def lawyer_consultations(request):
    status_filter = request.GET.get('status', '')
    qs = request.user.lawyer_consultations.select_related('user').order_by('-created_at')
    filtered = qs.filter(status=status_filter) if status_filter else qs
    paginator = Paginator(filtered, 15)
    return render(request, 'chatapp/lawyer_consultations.html', {
        'consultations':   paginator.get_page(request.GET.get('page', 1)),
        'status_choices':  Consultation.STATUS_CHOICES,
        'current_status':  status_filter,
        'lawyer_profile':  request.user.lawyer_profile,
        'pending_count':   qs.filter(status='pending').count(),
        'accepted_count':  qs.filter(status='accepted').count(),
    })


@login_required
@user_passes_test(is_lawyer)
@require_POST
def respond_consultation(request, consultation_id):
    consultation = get_object_or_404(Consultation, id=consultation_id, lawyer=request.user)
    response_text = request.POST.get('response', '')
    
    if not response_text:
        return JsonResponse({'error': 'الرجاء كتابة رد'}, status=400)

    # Save the response
    consultation.response = response_text
    consultation.status = request.POST.get('status', 'accepted')
    consultation.response_at = timezone.now()
    consultation.save()
    
    # ========== SEND EMAIL TO USER ==========
    try:
        user_email = consultation.user.email
        user_name = consultation.user.get_full_name() or consultation.user.username
        lawyer_name = request.user.get_full_name() or request.user.username
        lawyer_profile = request.user.lawyer_profile
        
        # Build URLs
        consultation_url = request.build_absolute_uri(
            reverse('consultation_detail', args=[consultation.id])
        )
        
        # Email subject based on status
        if consultation.status == 'accepted':
            status_text = "تم قبول الاستشارة"
            status_color = "#4CAF50"
        elif consultation.status == 'completed':
            status_text = "تم إكمال الاستشارة"
            status_color = "#2196F3"
        else:
            status_text = "تم الرد على الاستشارة"
            status_color = "#b8965a"
        
        subject = f"📩 {status_text} - {consultation.title}"
        
        # HTML Email
        html_message = f"""
        <html dir="rtl">
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px; }}
                .header {{ background: linear-gradient(135deg, #0b1628, #b8965a); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 20px; }}
                .response-box {{ background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 15px 0; border-right: 4px solid #b8965a; }}
                .status-box {{ background: #e8f5e9; padding: 15px; border-radius: 8px; margin: 15px 0; }}
                .lawyer-info {{ background: #fff3e0; padding: 15px; border-radius: 8px; margin: 15px 0; }}
                .button {{ display: inline-block; background: #b8965a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
                .footer {{ font-size: 12px; color: #666; text-align: center; margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; }}
                .status-badge {{ display: inline-block; background: {status_color}; color: white; padding: 5px 10px; border-radius: 5px; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>📩 رد على استشارتك القانونية</h2>
                </div>
                <div class="content">
                    <p>السلام عليكم، <strong>{user_name}</strong></p>
                    <p>قام المحامي <strong>{lawyer_name}</strong> بالرد على استشارتك "<strong>{consultation.title}</strong>".</p>
                    
                    <div class="status-box">
                        <h3>📋 حالة الاستشارة:</h3>
                        <p><span class="status-badge">{status_text}</span></p>
                    </div>
                    
                    <div class="lawyer-info">
                        <h3>⚖️ معلومات المحامي:</h3>
                        <p><strong>الاسم:</strong> {lawyer_name}</p>
                        <p><strong>التخصص:</strong> {lawyer_profile.get_specialization_display()}</p>
                        <p><strong>سنوات الخبرة:</strong> {lawyer_profile.experience_years} سنة</p>
                        <p><strong>مكتب:</strong> {lawyer_profile.office_name or 'غير محدد'}</p>
                        <p><strong>الهاتف:</strong> {lawyer_profile.office_phone or 'غير متوفر'}</p>
                    </div>
                    
                    <div class="response-box">
                        <h3>📝 رد المحامي:</h3>
                        <p style="white-space: pre-wrap;">{response_text}</p>
                    </div>
                    
                    <p>لعرض الرد كاملاً والتواصل مع المحامي:</p>
                    <p style="text-align: center;">
                        <a href="{consultation_url}" class="button">🔗 عرض التفاصيل والرد</a>
                    </p>
                    
                    <p><strong>ملاحظات مهمة:</strong></p>
                    <ul>
                        <li>يمكنك الرد على المحامي من خلال نفس الصفحة</li>
                        <li>يمكنك إرفاق ملفات أو مستندات إضافية</li>
                        <li>سيتم إشعارك بأي تحديثات جديدة على الاستشارة</li>
                    </ul>
                </div>
                <div class="footer">
                    <p>هذا بريد تلقائي من منصة المستشار القانوني السوري</p>
                    <p>للتواصل مع الدعم الفني، يرجى زيارة صفحة التواصل</p>
                    <p>© 2024 المستشار القانوني السوري - جميع الحقوق محفوظة</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        plain_message = f"""
السلام عليكم {user_name}

قام المحامي {lawyer_name} بالرد على استشارتك "{consultation.title}".

حالة الاستشارة: {status_text}

معلومات المحامي:
- الاسم: {lawyer_name}
- التخصص: {lawyer_profile.get_specialization_display()}
- سنوات الخبرة: {lawyer_profile.experience_years}
- المكتب: {lawyer_profile.office_name or 'غير محدد'}
- الهاتف: {lawyer_profile.office_phone or 'غير متوفر'}

رد المحامي:
{response_text}

لعرض الرد كاملاً:
{consultation_url}

مع تحيات,
المستشار القانوني السوري
"""
        
        # Send the email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            fail_silently=False,
            html_message=html_message,
        )
        
        logger.info(f"تم إرسال رد المحامي إلى البريد الإلكتروني للمستخدم {user_email} للاستشارة #{consultation.id}")
        
    except Exception as e:
        logger.error(f"فشل إرسال البريد الإلكتروني للمستخدم: {e}")
        # Don't return error to lawyer, just log it
        # The response was still saved successfully
    
    return JsonResponse({'success': True, 'message': 'تم إرسال الرد بنجاح وتم إشعار المستخدم'})

@login_required
@user_passes_test(is_lawyer)
def lawyer_profile_edit(request):
    lawyer_profile = request.user.lawyer_profile
    if request.method == 'POST':
        request.user.first_name = request.POST.get('first_name', '')
        request.user.last_name = request.POST.get('last_name', '')
        request.user.email = request.POST.get('email', '')
        request.user.save()

        profile = request.user.profile
        profile.phone = request.POST.get('phone', '')
        if request.FILES.get('avatar'):
            profile.avatar = request.FILES['avatar']
        profile.save()

        lawyer_profile.office_name = request.POST.get('office_name', '')
        lawyer_profile.office_address = request.POST.get('office_address', '')
        lawyer_profile.office_phone = request.POST.get('office_phone', '')
        lawyer_profile.office_email = request.POST.get('office_email', '')
        lawyer_profile.specialization = request.POST.get('specialization', '')
        lawyer_profile.experience_years = request.POST.get('experience_years', 0)
        lawyer_profile.consultation_fee = request.POST.get('consultation_fee', 0)
        lawyer_profile.description = request.POST.get('description', '')
        lawyer_profile.languages = request.POST.get('languages', 'العربية')
        lawyer_profile.is_available = request.POST.get('is_available') == 'on'

        lat = request.POST.get('latitude')
        lng = request.POST.get('longitude')
        if lat and lng:
            try:
                lawyer_profile.latitude = float(lat)
                lawyer_profile.longitude = float(lng)
            except (ValueError, TypeError):
                pass
        else:
            address = lawyer_profile.office_address
            if address:
                try:
                    lat, lng = get_coordinates(address)
                    if lat and lng:
                        lawyer_profile.latitude = lat
                        lawyer_profile.longitude = lng
                except Exception as e:
                    logger.error(f"فشل الإحداثيات: {e}")

        lawyer_profile.save()
        return JsonResponse({'success': True, 'message': 'تم حفظ التغييرات بنجاح'})

    return render(request, 'chatapp/lawyer_profile_edit.html', {
        'lawyer_profile': lawyer_profile,
        'specializations': LawyerProfile.SPECIALIZATIONS,
        'MAPTILER_API_KEY': settings.MAPTILER_API_KEY,
    })


@login_required
@user_passes_test(is_lawyer)
def lawyer_feedback_to_admin(request):
    if request.method == 'POST':
        subject = request.POST.get('subject', '')
        message = request.POST.get('message', '')
        if not subject or not message:
            return JsonResponse({'error': 'الرجاء ملء جميع الحقول'}, status=400)

        feedback_type = request.POST.get('feedback_type', 'other')
        Feedback.objects.create(
            user=request.user, feedback_type=feedback_type,
            subject=f"[محامي] {subject}", message=message,
            audio_file=request.FILES.get('audio_file') or None
        )
        return JsonResponse({'success': True, 'message': 'تم إرسال رسالتك للإدارة'})

    return render(request, 'chatapp/lawyer_feedback_form.html')


# ==================== Lawyer Pending ====================

def lawyer_pending(request):
    """صفحة انتظار موافقة الأدمن على المحامي"""
    # لو محامٍ موثق حاول يدخل هون، نوجهه لداشبورده
    if request.user.is_authenticated and is_lawyer(request.user):
        if request.user.lawyer_profile.is_verified:
            return redirect('lawyer_dashboard')
    return render(request, 'chatapp/lawyer_pending.html')


# ==================== Admin Dashboard ====================

@login_required
@user_passes_test(is_admin)
def admin_dashboard(request):
    last_30_days = timezone.now() - timedelta(days=30)
    last_month   = timezone.now() - timedelta(days=30)
    stats = {
        'total_users': User.objects.filter(profile__user_type='user').count(),
        'total_lawyers': LawyerProfile.objects.count(),
        'verified_lawyers': LawyerProfile.objects.filter(is_verified=True).count(),
        'pending_lawyers': LawyerProfile.objects.filter(is_verified=False).count(),
        'total_consultations': Consultation.objects.count(),
        'pending_consultations': Consultation.objects.filter(status='pending').count(),
        'total_feedbacks': Feedback.objects.count(),
        'unread_feedbacks': Feedback.objects.filter(is_read=False).count(),
        'total_documents': Document.objects.count(),
        'new_users_this_month': User.objects.filter(date_joined__gte=last_month).count(),
        'new_consultations_this_month': Consultation.objects.filter(created_at__gte=last_month).count(),
    }
    recent_activity = {
        'new_users':         User.objects.filter(date_joined__gte=last_30_days).count(),
        'new_lawyers':       LawyerProfile.objects.filter(created_at__gte=last_30_days).count(),
        'new_consultations': Consultation.objects.filter(created_at__gte=last_30_days).count(),
        'new_feedbacks':     Feedback.objects.filter(created_at__gte=last_30_days).count(),
    }
    return render(request, 'chatapp/admin_dashboard.html', {
        'stats': stats,
        'recent_activity': recent_activity,
        'recent_users': User.objects.order_by('-date_joined')[:5],
        'recent_lawyers': LawyerProfile.objects.select_related('user').order_by('-created_at')[:5],
        'recent_feedbacks': Feedback.objects.select_related('user').order_by('-created_at')[:8],
    })


@login_required
@user_passes_test(is_admin)
def admin_lawyers_management(request):
    status_filter = request.GET.get('status', '')
    search_query = request.GET.get('q', '')
    lawyers = LawyerProfile.objects.select_related('user').order_by('is_verified', '-created_at')

    if status_filter == 'verified':
        lawyers = lawyers.filter(is_verified=True)
    elif status_filter == 'pending':
        lawyers = lawyers.filter(is_verified=False)
    elif status_filter == 'unavailable':
        lawyers = lawyers.filter(is_available=False)

    if search_query:
        lawyers = lawyers.filter(
            Q(user__username__icontains=search_query) |
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(office_name__icontains=search_query)
        )

    paginator = Paginator(lawyers, 20)
    return render(request, 'chatapp/admin_lawyers.html', {
        'lawyers': paginator.get_page(request.GET.get('page', 1)),
        'current_status': status_filter,
        'pending_count':  LawyerProfile.objects.filter(is_verified=False).count(),
        'verified_count': LawyerProfile.objects.filter(is_verified=True).count(),
        'total_count':    LawyerProfile.objects.count(),
    })


@login_required
@user_passes_test(is_admin)
def admin_lawyer_edit(request, lawyer_id):
    lawyer_profile = get_object_or_404(LawyerProfile, id=lawyer_id)
    if request.method == 'POST':
        # User account fields
        user = lawyer_profile.user
        user.first_name = request.POST.get('first_name', user.first_name).strip()
        user.last_name  = request.POST.get('last_name',  user.last_name).strip()
        user.username   = request.POST.get('username',   user.username).strip() or user.username
        user.email      = request.POST.get('email',      user.email).strip()
        user.save()

        # Lawyer profile fields
        lawyer_profile.is_verified     = request.POST.get('is_verified')  == 'on'
        lawyer_profile.is_available    = request.POST.get('is_available') == 'on'
        lawyer_profile.license_number  = request.POST.get('license_number', '').strip()
        lawyer_profile.specialization  = request.POST.get('specialization', '')
        lawyer_profile.experience_years= int(request.POST.get('experience_years', 0) or 0)
        lawyer_profile.languages       = request.POST.get('languages', 'العربية').strip()
        lawyer_profile.description     = request.POST.get('description', '').strip()
        lawyer_profile.office_name     = request.POST.get('office_name', '').strip()
        lawyer_profile.office_address  = request.POST.get('office_address', '').strip()
        lawyer_profile.office_phone    = request.POST.get('office_phone', '').strip()
        lawyer_profile.mobile_phone    = request.POST.get('mobile_phone', '').strip()
        lawyer_profile.office_email    = request.POST.get('office_email', '').strip()
        if hasattr(lawyer_profile, 'city'):
            lawyer_profile.city        = request.POST.get('city', '').strip()

        lat = request.POST.get('latitude')
        lng = request.POST.get('longitude')
        if lat and lng:
            try:
                lawyer_profile.latitude = float(lat)
                lawyer_profile.longitude = float(lng)
            except (ValueError, TypeError):
                pass

        lawyer_profile.save()
        return JsonResponse({'success': True, 'message': 'تم حفظ التغييرات'})

    return render(request, 'chatapp/admin_lawyer_edit.html', {
        'lawyer_profile': lawyer_profile,
        'specializations': LawyerProfile.SPECIALIZATIONS,
        'MAPTILER_API_KEY': settings.MAPTILER_API_KEY,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_verify_lawyer(request, lawyer_id):
    lawyer_profile = get_object_or_404(LawyerProfile, id=lawyer_id)
    action = request.POST.get('action', 'verify')
    lawyer_profile.is_verified = (action == 'verify')
    lawyer_profile.save()
    return JsonResponse({'success': True, 'is_verified': lawyer_profile.is_verified})


@login_required
@user_passes_test(is_admin)
def admin_feedbacks(request):
    status_filter = request.GET.get('status', '')
    type_filter = request.GET.get('type', '')
    feedbacks = Feedback.objects.select_related('user').order_by('-created_at')

    if status_filter == 'unread':
        feedbacks = feedbacks.filter(is_read=False)
    elif status_filter == 'resolved':
        feedbacks = feedbacks.filter(is_resolved=True)
    elif status_filter == 'pending':
        feedbacks = feedbacks.filter(is_read=True, is_resolved=False)

    if type_filter:
        feedbacks = feedbacks.filter(feedback_type=type_filter)

    paginator = Paginator(feedbacks, 20)
    return render(request, 'chatapp/admin_feedbacks.html', {
        'feedbacks': paginator.get_page(request.GET.get('page', 1)),
        'current_status': status_filter,
        'current_type': type_filter,
        'feedback_types': Feedback.FEEDBACK_TYPES,
    })


@login_required
@user_passes_test(is_admin)
def admin_feedback_detail(request, feedback_id):
    feedback = get_object_or_404(Feedback.objects.select_related('user'), id=feedback_id)
    if not feedback.is_read:
        feedback.is_read = True
        feedback.save()

    if request.method == 'POST':
        feedback.admin_response = request.POST.get('admin_response', '')
        if request.POST.get('mark_resolved') == 'on' and not feedback.is_resolved:
            feedback.is_resolved = True
            feedback.resolved_at = timezone.now()
        feedback.save()
        return JsonResponse({'success': True, 'message': 'تم حفظ الرد'})

    return render(request, 'chatapp/admin_feedback_detail.html', {'feedback': feedback})


@login_required
@user_passes_test(is_admin)
def admin_documents(request):
    """إدارة الوثائق في قاعدة بيانات RAG"""
    search_query = request.GET.get('q', '')
    documents = Document.objects.select_related('uploaded_by').order_by('-uploaded_at')

    if search_query:
        documents = documents.filter(
            Q(title__icontains=search_query) |
            Q(extracted_text__icontains=search_query)
        )

    # إحصائيات LegalArticle لكل وثيقة
    docs_with_counts = documents.annotate(
        db_articles=Count('articles', distinct=True)
    )

    paginator = Paginator(docs_with_counts, 15)
    total_articles = LegalArticle.objects.count()

    return render(request, 'chatapp/admin_documents.html', {
        'documents':      paginator.get_page(request.GET.get('page', 1)),
        'search_query':   search_query,
        'total_docs':     Document.objects.count(),
        'total_articles': total_articles,
    })


@login_required
@user_passes_test(is_admin)
def admin_statistics(request):
    last_30_days = timezone.now() - timedelta(days=30)
    lawyers_by_specialization = LawyerProfile.objects.values('specialization').annotate(count=Count('id')).order_by('-count')
    top_lawyers = LawyerProfile.objects.filter(is_verified=True).order_by('-rating', '-total_reviews')[:10]
    consultations_by_status = Consultation.objects.values('status').annotate(count=Count('id'))
    recent_activity = {
        'new_users':         User.objects.filter(date_joined__gte=last_30_days).count(),
        'new_lawyers':       LawyerProfile.objects.filter(created_at__gte=last_30_days).count(),
        'new_consultations': Consultation.objects.filter(created_at__gte=last_30_days).count(),
        'new_feedbacks':     Feedback.objects.filter(created_at__gte=last_30_days).count(),
    }
    return render(request, 'chatapp/admin_statistics.html', {
        'lawyers_by_specialization': lawyers_by_specialization,
        'top_lawyers':               top_lawyers,
        'consultations_by_status':   consultations_by_status,
        'recent_activity':           recent_activity,
    })


@login_required
@user_passes_test(is_admin)
def admin_rag_status(request):
    """
    صفحة تشخيص كاملة لحالة نظام RAG:
    - اختبار اتصال OpenAI
    - اختبار اتصال Pinecone
    - إحصائيات الـ vectors
    - اختبار بحث مباشر
    """
    status = {
        'openai':         {'ok': False, 'msg': ''},
        'pinecone':       {'ok': False, 'msg': '', 'vector_count': 0},
        'docs_in_db':     Document.objects.count(),
        'total_articles': LegalArticle.objects.count(),
        'indexed_docs':   Document.objects.filter(is_indexed=True).count(),
        'test_query':     None,
    }

    # اختبار OpenAI
    try:
        from openai import OpenAI as _OAI
        _OAI(api_key=settings.OPENAI_API_KEY).embeddings.create(
            model="text-embedding-3-large", input="test")
        status['openai'] = {'ok': True, 'msg': 'متصل ✓'}
    except Exception as e:
        status['openai'] = {'ok': False, 'msg': str(e)[:120]}

    # اختبار Pinecone
    try:
        from pinecone import Pinecone as _PC
        idx2  = _PC(api_key=settings.PINECONE_API_KEY).Index(settings.PINECONE_INDEX_NAME)
        stats = idx2.describe_index_stats()
        status['pinecone'] = {
            'ok': True,
            'msg': f'متصل ✓ — {settings.PINECONE_INDEX_NAME}',
            'vector_count': stats.get('total_vector_count', 0),
        }
    except Exception as e:
        status['pinecone'] = {'ok': False, 'msg': str(e)[:120], 'vector_count': 0}

    # اختبار بحث
    test_q = request.GET.get('q', '')
    if test_q and status['openai']['ok'] and status['pinecone']['ok']:
        try:
            from .rag_utils import search_similar_chunks
            results = search_similar_chunks(test_q, top_k=5)
            status['test_query'] = {'query': test_q, 'results': results, 'count': len(results)}
        except Exception as e:
            status['test_query'] = {'query': test_q, 'error': str(e), 'count': 0}

    return render(request, 'chatapp/admin_rag_status.html', {'status': status})


# ==================== JSON APIs ====================

@login_required
def lawyers_list_json(request):
    lawyers = LawyerProfile.objects.filter(is_verified=True, is_available=True).select_related('user')[:20]
    return JsonResponse({'lawyers': [
        {
            'id': l.id,
            'name': l.user.get_full_name() or l.user.username,
            'specialization': l.get_specialization_display(),
            'rating': float(l.rating),
            'reviews': l.total_reviews,
            'lat': float(l.latitude) if l.latitude else None,
            'lng': float(l.longitude) if l.longitude else None,
        }
        for l in lawyers
    ]})


@login_required
def lawyer_detail_json(request, lawyer_id):
    l = get_object_or_404(LawyerProfile.objects.select_related('user'), id=lawyer_id)
    return JsonResponse({
        'id': l.id,
        'name': l.user.get_full_name() or l.user.username,
        'specialization': l.get_specialization_display(),
        'experience': l.experience_years,
        'rating': float(l.rating),
        'reviews': l.total_reviews,
        'fee': float(l.consultation_fee),
        'address': l.office_address,
        'phone': l.office_phone,
        'description': l.description,
        'is_verified': l.is_verified,
    })


# ==================== Admin — Official Documents CRUD ====================

@login_required
@user_passes_test(is_admin)
def admin_official_docs(request):
    categories = (
        OfficialDocumentCategory.objects
        .prefetch_related('items')
        .order_by('order', 'name')
    )
    return render(request, 'chatapp/admin_official_docs.html', {
        'categories':  categories,
        'total_cats':  categories.count(),
        'total_items': OfficialDocumentItem.objects.count(),
        'icons_list':  ['📋','💍','👨‍👩‍👦','👤','📄','💼','🚗','🏠','🛂','🎓','📜','⚖️'],
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_official_doc_cat_add(request):
    name        = request.POST.get('name', '').strip()
    icon        = request.POST.get('icon', '📋').strip() or '📋'
    description = request.POST.get('description', '').strip()
    order       = request.POST.get('order', '0')
    is_active   = request.POST.get('is_active', 'true') == 'true'
    try:
        order = int(order)
    except (ValueError, TypeError):
        order = 0
    color = request.POST.get('color', 'linear-gradient(135deg,#0b1628,#b8965a)').strip()
    if not name:
        return JsonResponse({'success': False, 'error': 'الاسم مطلوب'}, status=400)
    cat = OfficialDocumentCategory.objects.create(
        name=name, icon=icon, color=color, description=description,
        order=order, is_active=is_active,
    )
    return JsonResponse({
        'success': True,
        'id': cat.id, 'name': cat.name, 'icon': cat.icon, 'color': cat.color,
        'description': cat.description, 'order': cat.order,
        'is_active': cat.is_active,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_official_doc_cat_edit(request, cat_id):
    cat = get_object_or_404(OfficialDocumentCategory, id=cat_id)
    cat.name        = request.POST.get('name', cat.name).strip() or cat.name
    cat.icon        = request.POST.get('icon', cat.icon).strip() or cat.icon
    cat.color       = request.POST.get('color', cat.color).strip() or cat.color
    cat.description = request.POST.get('description', cat.description).strip()
    cat.is_active   = request.POST.get('is_active', 'true') == 'true'
    try:
        cat.order = int(request.POST.get('order', cat.order))
    except (ValueError, TypeError):
        pass
    cat.save()
    return JsonResponse({
        'success': True,
        'id': cat.id, 'name': cat.name, 'icon': cat.icon, 'color': cat.color,
        'description': cat.description, 'order': cat.order,
        'is_active': cat.is_active,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_official_doc_cat_delete(request, cat_id):
    cat = get_object_or_404(OfficialDocumentCategory, id=cat_id)
    cat.delete()
    return JsonResponse({'success': True})


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_official_doc_item_add(request):
    cat_id      = request.POST.get('category_id')
    name        = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    is_required = request.POST.get('is_required', 'true') == 'true'
    order       = request.POST.get('order', '0')
    try:
        order = int(order)
    except (ValueError, TypeError):
        order = 0
    if not name:
        return JsonResponse({'success': False, 'error': 'الاسم مطلوب'}, status=400)
    cat = get_object_or_404(OfficialDocumentCategory, id=cat_id)
    item = OfficialDocumentItem.objects.create(
        category=cat, name=name, description=description,
        is_required=is_required, order=order,
    )
    return JsonResponse({
        'success': True,
        'id': item.id, 'name': item.name, 'description': item.description,
        'is_required': item.is_required, 'order': item.order,
        'category_id': cat.id,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_official_doc_item_edit(request, item_id):
    item = get_object_or_404(OfficialDocumentItem, id=item_id)
    item.name        = request.POST.get('name', item.name).strip() or item.name
    item.description = request.POST.get('description', item.description).strip()
    item.is_required = request.POST.get('is_required', 'true') == 'true'
    try:
        item.order = int(request.POST.get('order', item.order))
    except (ValueError, TypeError):
        pass
    item.save()
    return JsonResponse({
        'success': True,
        'id': item.id, 'name': item.name, 'description': item.description,
        'is_required': item.is_required, 'order': item.order,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_official_doc_item_delete(request, item_id):
    item = get_object_or_404(OfficialDocumentItem, id=item_id)
    cat_id = item.category_id
    item.delete()
    return JsonResponse({'success': True, 'category_id': cat_id})

# ══════════════════════════════════════════════════════════
#  إدارة منشئ الوثائق القانونية
# ══════════════════════════════════════════════════════════

# الأنواع الافتراضية المُضمَّنة في النظام
_DEFAULT_LEGAL_TYPES = [
    ('sale_property',              'عقد بيع عقار',          '🏠', 0),
    ('sale_vehicle',               'عقد بيع سيارة',         '🚗', 1),
    ('sale_goods',                 'عقد بيع بضاعة',         '📦', 2),
    ('rent_residential',           'عقد إيجار سكني',        '🏡', 3),
    ('rent_commercial',            'عقد إيجار تجاري',       '🏢', 4),
    ('employment',                 'عقد عمل',                '💼', 5),
    ('services',                   'عقد تقديم خدمات',       '🔧', 6),
    ('contractor',                 'عقد مقاولة',             '🏗️', 7),
    ('loan',                       'عقد قرض مالي',          '💰', 8),
    ('mortgage',                   'سند رهن عقاري',         '🏦', 9),
    ('partnership',                'عقد شراكة تجارية',      '🤝', 10),
    ('power_of_attorney',          'وكالة قانونية عامة',    '📜', 11),
    ('power_of_attorney_special',  'وكالة خاصة',            '📋', 12),
    ('inheritance_acknowledgment', 'إقرار بالإرث',          '⚖️', 13),
    ('debt_acknowledgment',        'إقرار بالدين',          '💳', 14),
    ('court_settlement',           'صلح قضائي / تسوية',    '🔨', 15),
    ('agency_commercial',          'عقد وكالة تجارية',      '🏪', 16),
    ('nda',                        'اتفاقية سرية NDA',      '🔒', 17),
    ('supply',                     'عقد توريد',              '🚚', 18),
]


@login_required
@user_passes_test(is_admin)
def admin_legal_docs(request):
    """لوحة إدارة منشئ الوثائق القانونية"""
    # تهيئة الأنواع الافتراضية إن لم تكن موجودة
    if LegalDocumentType.objects.count() == 0:
        for slug, name, icon, order in _DEFAULT_LEGAL_TYPES:
            LegalDocumentType.objects.get_or_create(slug=slug, defaults={
                'name': name, 'icon': icon, 'order': order, 'is_active': True,
            })

    doc_types   = LegalDocumentType.objects.all()
    active_cnt  = doc_types.filter(is_active=True).count()
    total_gen   = GeneratedDocument.objects.count()
    total_users = GeneratedDocument.objects.values('user').distinct().count()

    # توزيع الوثائق حسب النوع
    type_stats = (
        GeneratedDocument.objects
        .values('doc_type')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')
    )
    type_stats_map = {t['doc_type']: t['cnt'] for t in type_stats}

    # أحدث الوثائق المنشأة
    recent_docs = (
        GeneratedDocument.objects
        .select_related('user')
        .order_by('-created_at')[:20]
    )

    return render(request, 'chatapp/admin_legal_docs.html', {
        'doc_types':          doc_types,
        'active_cnt':         active_cnt,
        'total_gen':          total_gen,
        'total_users':        total_users,
        'type_stats_map':     type_stats_map,
        'type_stats_map_json': json.dumps(type_stats_map, ensure_ascii=False),
        'recent_docs':        recent_docs,
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_legal_doc_type_save(request, type_id):
    """تعديل بيانات نوع وثيقة قانونية"""
    dt          = get_object_or_404(LegalDocumentType, id=type_id)
    dt.name     = request.POST.get('name', dt.name).strip() or dt.name
    dt.icon     = request.POST.get('icon', dt.icon).strip() or dt.icon
    dt.description = request.POST.get('description', '').strip()
    dt.order    = int(request.POST.get('order', dt.order) or dt.order)
    dt.save()
    return JsonResponse({'success': True, 'name': dt.name, 'icon': dt.icon})


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_legal_doc_type_toggle(request, type_id):
    """تفعيل/تعطيل نوع وثيقة"""
    dt = get_object_or_404(LegalDocumentType, id=type_id)
    dt.is_active = not dt.is_active
    dt.save()
    return JsonResponse({'success': True, 'is_active': dt.is_active})


@login_required
@user_passes_test(is_admin)
def admin_generated_doc_view(request, doc_id):
    """عرض وثيقة مُنشأة"""
    doc = get_object_or_404(GeneratedDocument, id=doc_id)
    return JsonResponse({
        'id':           doc.id,
        'doc_type':     doc.doc_type,
        'doc_type_display': doc.get_doc_type_display(),
        'title':        doc.title,
        'html_content': doc.html_content,
        'user':         doc.user.get_full_name() or doc.user.username,  # get_full_name is a method
        'created_at':   doc.created_at.strftime('%Y-%m-%d %H:%M'),
    })


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_generated_doc_delete(request, doc_id):
    """حذف وثيقة مُنشأة"""
    doc = get_object_or_404(GeneratedDocument, id=doc_id)
    doc.delete()
    return JsonResponse({'success': True})


# ══════════════════════════════════════════════════════════
#  إعادة تعيين كلمة المرور — نسيت كلمة المرور
# ══════════════════════════════════════════════════════════
import random
import time as _time
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt

import random
import time as _time
import traceback
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# ==================== Password Reset (Simplified) ====================
import random
import time as _time
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import make_password

@csrf_exempt
@require_POST
def password_forgot(request):
    """Send reset code to email"""
    try:
        email = request.POST.get('email', '').strip().lower()
        
        if not email:
            return JsonResponse({'success': False, 'error': 'البريد الإلكتروني مطلوب'}, status=400)
        
        # Check if user exists
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't reveal if user exists for security
            return JsonResponse({'success': True, 'message': 'إذا كان البريد مسجلاً، سيصلك الكود'})
        
        # Generate 6-digit code
        code = f"{random.randint(0, 999999):06d}"
        
        # Save to session (make sure session works)
        request.session['reset_code'] = code
        request.session['reset_email'] = email
        request.session['reset_time'] = int(_time.time())
        request.session.modified = True
        
        # For testing - print code to console instead of sending email
        # Remove this when email works
        print(f"\n{'='*50}")
        print(f"RESET CODE for {email}: {code}")
        print(f"{'='*50}\n")
        
        # Try to send email (will fail if not configured, but we have console fallback)
        try:
            send_mail(
                'Reset Your Password',
                f'Your verification code is: {code}\n\nThis code expires in 10 minutes.',
                settings.DEFAULT_FROM_EMAIL or 'noreply@example.com',
                [email],
                fail_silently=True,  # Don't crash if email fails
            )
        except:
            pass  # Email failed but we already printed to console
        
        return JsonResponse({'success': True, 'message': 'تم إرسال الكود'})
        
    except Exception as e:
        print(f"Password reset error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_POST
def verify_reset_code(request):
    """Verify the reset code"""
    try:
        code = request.POST.get('code', '').strip()
        saved_code = request.session.get('reset_code')
        reset_time = request.session.get('reset_time', 0)
        
        if not saved_code:
            return JsonResponse({'success': False, 'error': 'لم يتم طلب إعادة تعيين'}, status=400)
        
        # Check if code expired (10 minutes = 600 seconds)
        if int(_time.time()) - reset_time > 600:
            return JsonResponse({'success': False, 'error': 'انتهت صلاحية الكود'}, status=400)
        
        if code != saved_code:
            return JsonResponse({'success': False, 'error': 'الكود غير صحيح'}, status=400)
        
        # Code is valid
        request.session['reset_verified'] = True
        request.session.modified = True
        
        return JsonResponse({'success': True, 'message': 'تم التحقق'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
@csrf_exempt
@require_POST
def reset_password(request):
    """Reset the password"""
    try:
        # Check if verified
        if not request.session.get('reset_verified'):
            return JsonResponse({'success': False, 'error': 'لم يتم التحقق من الكود'}, status=400)
        
        email = request.session.get('reset_email')
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')
        
        if not email:
            return JsonResponse({'success': False, 'error': 'جلسة غير صالحة'}, status=400)
        
        if len(password1) < 6:
            return JsonResponse({'success': False, 'error': 'كلمة المرور قصيرة جداً'}, status=400)
        
        if password1 != password2:
            return JsonResponse({'success': False, 'error': 'كلمتا المرور غير متطابقتين'}, status=400)
        
        try:
            user = User.objects.get(email=email)
            user.set_password(password1)
            user.save()
            
            # Clear session
            request.session.flush()
            
            return JsonResponse({'success': True, 'message': 'تم تغيير كلمة المرور بنجاح'})
            
        except User.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'المستخدم غير موجود'}, status=400)
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)