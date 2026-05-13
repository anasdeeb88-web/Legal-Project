import json
import logging
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
    LawyerReview, Feedback, Message
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


# ==================== Authentication Views ====================

def register(request):
    """تسجيل مستخدم عادي جديد"""
    if request.user.is_authenticated:
        return redirect('index')

    email_error = None

    if request.method == "POST":
        form = UserCreationForm(request.POST)
        email = request.POST.get('email', '').strip()

        # التحقق من الإيميل
        if not email:
            email_error = "البريد الإلكتروني مطلوب."
        elif '@' not in email or '.' not in email.split('@')[-1]:
            email_error = "أدخل بريداً إلكترونياً صحيحاً."
        elif User.objects.filter(email=email).exists():
            email_error = "هذا البريد الإلكتروني مستخدم بالفعل."

        if form.is_valid() and not email_error:
            user = form.save(commit=False)
            user.email = email
            user.save()
            UserProfile.objects.create(user=user, user_type='user')
            login(request, user)
            return smart_redirect(user)
    else:
        form = UserCreationForm()

    return render(request, "register.html", {"form": form, "email_error": email_error})


def lawyer_register(request):
    """تسجيل محامي جديد"""
    if request.user.is_authenticated:
        return redirect('index')
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            user.first_name = request.POST.get('first_name', '')
            user.last_name = request.POST.get('last_name', '')
            user.email = request.POST.get('email', '')
            user.save()

            UserProfile.objects.create(user=user, user_type='lawyer')

            latitude = request.POST.get('latitude')
            longitude = request.POST.get('longitude')
            lat = None
            lng = None
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

            LawyerProfile.objects.create(
                user=user,
                license_number=request.POST.get('license_number', ''),
                specialization=request.POST.get('specialization', 'civil'),
                experience_years=request.POST.get('experience_years', 0),
                office_name=request.POST.get('office_name', ''),
                office_address=request.POST.get('office_address', ''),
                office_phone=request.POST.get('office_phone', ''),
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
        "form": form,
        "specializations": LawyerProfile.SPECIALIZATIONS,
        "MAPTILER_API_KEY": settings.MAPTILER_API_KEY,
    })


# ==================== Main Pages ====================

@login_required
def index(request):
    context = {
        'total_lawyers': LawyerProfile.objects.filter(is_verified=True).count(),
        'user_consultations': request.user.consultations.count(),
        'is_lawyer': is_lawyer(request.user),
        'is_admin': is_admin(request.user),
    }
    return render(request, "chatapp/index.html", context)


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
        'success':       False,
        'doc_id':        doc.id,
        'title':         doc.title,
        'text_len':      0,
        'chunks_stored': 0,
        'error':         None,
        'stage':         'created',
    }

    try:
        # المرحلة 1: استخراج النص
        result['stage'] = 'extracting'
        extracted_text = _extract_text_from_document(doc)
        doc.extracted_text = extracted_text
        doc.save()
        result['text_len'] = len(extracted_text)

        if not extracted_text.strip():
            result['error'] = 'النص فارغ بعد الاستخراج — تأكد أن الـ PDF يحتوي نصاً وليس صوراً فقط'
            logger.warning(f"الوثيقة #{doc.id}: {result['error']}")
        else:
            # المرحلة 2: الفهرسة في Pinecone
            result['stage'] = 'indexing'
            chunks_stored = store_document_in_pinecone(
                doc.id, extracted_text, doc_title=doc.title
            )
            result['chunks_stored'] = chunks_stored
            if chunks_stored == 0:
                result['error'] = 'تم استخراج النص لكن فشل التخزين في Pinecone — تحقق من مفاتيح API في .env'
            else:
                result['success'] = True
                logger.info(f"الوثيقة #{doc.id} '{doc.title}': خُزِّن {chunks_stored} مقطع")

    except Exception as e:
        result['error'] = f"خطأ في مرحلة {result['stage']}: {str(e)}"
        logger.error(f"فشل معالجة الوثيقة {doc.id}: {e}", exc_info=True)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return JsonResponse(result)

    # للـ form العادي: أضف message واعمل redirect
    if result['success']:
        from django.contrib import messages
        messages.success(request, f"✅ '{doc.title}' رُفعت وفُهرست بنجاح ({result['chunks_stored']} مقطع)")
    else:
        from django.contrib import messages
        messages.error(request, f"⚠️ '{doc.title}' رُفعت لكن فشلت الفهرسة: {result['error']}")

    return redirect("admin_documents")


@login_required
@require_POST
def delete_document(request, doc_id):
    """حذف وثيقة (للمدير فقط) — يحذفها من DB ومن Pinecone"""
    if not is_admin(request.user):
        return HttpResponseForbidden()
    doc = get_object_or_404(Document, id=doc_id)

    # حذف vectors من Pinecone
    try:
        from .rag_utils import index as pinecone_index
        # نبحث عن كل vectors تخص هذه الوثيقة ونحذفها
        pinecone_index.delete(filter={"doc_id": str(doc_id)})
        logger.info(f"تم حذف vectors الوثيقة #{doc_id} من Pinecone")
    except Exception as e:
        logger.warning(f"فشل حذف vectors الوثيقة #{doc_id} من Pinecone: {e}")

    doc.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def reindex_document(request, doc_id):
    """إعادة فهرسة وثيقة موجودة في Pinecone (للمدير فقط)"""
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

        # حذف القديم من Pinecone أولاً
        try:
            from .rag_utils import index as pinecone_index
            pinecone_index.delete(filter={"doc_id": str(doc_id)})
        except Exception as e:
            logger.warning(f"فشل حذف vectors قديمة: {e}")

        # فهرسة جديدة
        chunks_stored = store_document_in_pinecone(
            doc.id, extracted_text, doc_title=doc.title
        )
        return JsonResponse({
            'success': True,
            'chunks': chunks_stored,
            'text_len': len(extracted_text),
        })
    except Exception as e:
        logger.error(f"فشل إعادة فهرسة الوثيقة #{doc_id}: {e}")
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
    try:
        reader = PdfReader(pdf_path)
        return "\n".join([p.extract_text() or "" for p in reader.pages])
    except Exception as e:
        logger.error(f"فشل استخراج PDF: {e}")
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
                title  = chunk.get("doc_title", "وثيقة")
                header = chunk.get("header", "")
                text   = chunk.get("text", "")
                score  = chunk.get("score", 0)
                label  = title + (f" — {header}" if header else "")
                context_parts.append(
                    f"【مقطع {i} | {label} | دقة: {score}】\n{text}"
                )
            else:
                context_parts.append(f"【مقطع {i}】\n{chunk}")
        context_text = "\n\n---\n\n".join(context_parts)
        has_context  = True
    else:
        context_text = ""
        has_context  = False

    # ── System Prompt ──
    system_prompt = """\
أنت مساعد معلوماتي ذكي يعتمد على الوثائق المُحمَّلة في قاعدة البيانات.

## قواعد الإجابة:

**عند توفر وثائق ذات صلة:**
- اعتمد فقط على المعلومات الواردة في مقاطع السياق المُقدَّمة.
- اذكر المصدر باختصار عند الاقتباس (مثال: "وفق [اسم الوثيقة]...").
- إذا تعددت الوثائق المتعلقة بالسؤال، اجمع المعلومات منها جميعاً.
- رتّب إجابتك: تعريف → تفاصيل → استثناءات إن وُجدت.

**عند غياب معلومات كافية:**
- صرّح بوضوح: "لا تتوفر في الوثائق الحالية معلومات كافية حول هذا الموضوع."
- لا تستعن بمعرفتك العامة لملء الفراغات.
- اقترح على المستخدم البحث في مصدر متخصص أو استشارة محامٍ.

**قواعد الأسلوب:**
- استخدم العربية الفصحى الواضحة.
- إذا كان السؤال عن مادة قانونية بعينها، اذكر نصها كاملاً ثم فسّرها.
- نبّه في نهاية الإجابة: هذه معلومات من الوثائق المتاحة ولا تُغني عن استشارة متخصص.
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
                'specializations': LawyerProfile.SPECIALIZATIONS,
                'MAPTILER_API_KEY': settings.MAPTILER_API_KEY,
            })
        except Exception as e:
            logger.error(f"فشل البحث الجغرافي: {e}")

    paginator = Paginator(lawyers, 12)
    context = {
        'lawyers': paginator.get_page(request.GET.get('page', 1)),
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


@login_required
def lawyer_detail(request, lawyer_id):
    lawyer = get_object_or_404(LawyerProfile.objects.select_related('user'), id=lawyer_id, is_verified=True)
    reviews = lawyer.reviews.select_related('user').order_by('-created_at')[:10]
    rating_distribution = {i: lawyer.reviews.filter(rating=i).count() for i in range(1, 6)}

    return render(request, 'chatapp/lawyer_detail.html', {
        'lawyer': lawyer,
        'reviews': reviews,
        'rating_distribution': rating_distribution,
        'can_review': not LawyerReview.objects.filter(lawyer=lawyer, user=request.user).exists(),
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
    return JsonResponse({'success': True, 'new_rating': float(lawyer.rating), 'total_reviews': lawyer.total_reviews})


# ==================== Consultations ====================

@login_required
@require_POST
def request_consultation(request, lawyer_id):
    lawyer_profile = get_object_or_404(LawyerProfile, id=lawyer_id, is_verified=True)
    title = request.POST.get('title', '')
    description = request.POST.get('description', '')
    audio_file = request.FILES.get('audio_file')

    if not title or not description:
        return JsonResponse({'error': 'الرجاء ملء جميع الحقول'}, status=400)

    consultation = Consultation.objects.create(
        user=request.user, lawyer=lawyer_profile.user,
        title=title, description=description,
        audio_file=audio_file if audio_file else None
    )

    if audio_file:
        try:
            consultation.audio_transcription = process_audio_file(audio_file, use_whisper=True)
            consultation.save()
        except Exception as e:
            logger.error(f"فشل تحويل الصوت: {e}")

    return JsonResponse({'success': True, 'consultation_id': consultation.id, 'message': 'تم إرسال الطلب بنجاح'})


@login_required
def my_consultations(request):
    consultations = request.user.consultations.select_related('lawyer').order_by('-created_at')
    paginator = Paginator(consultations, 10)
    return render(request, 'chatapp/consultations_list.html', {
        'consultations': paginator.get_page(request.GET.get('page', 1)),
        'title': 'استشاراتي'
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
def lawyer_dashboard(request):
    lawyer_profile = request.user.lawyer_profile
    stats = {
        'total_consultations': request.user.lawyer_consultations.count(),
        'pending_consultations': request.user.lawyer_consultations.filter(status='pending').count(),
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
    consultations = request.user.lawyer_consultations.select_related('user').order_by('-created_at')
    if status_filter:
        consultations = consultations.filter(status=status_filter)
    paginator = Paginator(consultations, 15)
    return render(request, 'chatapp/lawyer_consultations.html', {
        'consultations': paginator.get_page(request.GET.get('page', 1)),
        'status_choices': Consultation.STATUS_CHOICES,
        'current_status': status_filter,
    })


@login_required
@user_passes_test(is_lawyer)
@require_POST
def respond_consultation(request, consultation_id):
    consultation = get_object_or_404(Consultation, id=consultation_id, lawyer=request.user)
    response_text = request.POST.get('response', '')
    if not response_text:
        return JsonResponse({'error': 'الرجاء كتابة رد'}, status=400)

    consultation.response = response_text
    consultation.status = request.POST.get('status', 'accepted')
    consultation.response_at = timezone.now()
    consultation.save()
    return JsonResponse({'success': True, 'message': 'تم إرسال الرد بنجاح'})


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

        Feedback.objects.create(
            user=request.user, feedback_type='other',
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
    }
    return render(request, 'chatapp/admin_dashboard.html', {
        'stats': stats,
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
        lawyer_profile.is_verified = request.POST.get('is_verified') == 'on'
        lawyer_profile.is_available = request.POST.get('is_available') == 'on'
        lawyer_profile.license_number = request.POST.get('license_number', '')
        lawyer_profile.specialization = request.POST.get('specialization', '')
        lawyer_profile.experience_years = request.POST.get('experience_years', 0)
        lawyer_profile.office_name = request.POST.get('office_name', '')
        lawyer_profile.office_address = request.POST.get('office_address', '')
        lawyer_profile.office_phone = request.POST.get('office_phone', '')
        lawyer_profile.office_email = request.POST.get('office_email', '')
        lawyer_profile.consultation_fee = request.POST.get('consultation_fee', 0)
        lawyer_profile.description = request.POST.get('description', '')

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

    paginator = Paginator(documents, 15)
    return render(request, 'chatapp/admin_documents.html', {
        'documents': paginator.get_page(request.GET.get('page', 1)),
        'search_query': search_query,
        'total_docs': Document.objects.count(),
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
        'openai':   {'ok': False, 'msg': ''},
        'pinecone': {'ok': False, 'msg': '', 'vector_count': 0},
        'docs_in_db': Document.objects.count(),
        'test_query': None,
    }

    # اختبار OpenAI
    try:
        from openai import OpenAI as _OAI
        c = _OAI(api_key=settings.OPENAI_API_KEY)
        c.embeddings.create(model="text-embedding-3-large", input="test")
        status['openai'] = {'ok': True, 'msg': 'متصل ✓'}
    except Exception as e:
        status['openai'] = {'ok': False, 'msg': str(e)[:120]}

    # اختبار Pinecone
    try:
        from pinecone import Pinecone as _PC
        pc2 = _PC(api_key=settings.PINECONE_API_KEY)
        idx2 = pc2.Index(settings.PINECONE_INDEX_NAME)
        stats = idx2.describe_index_stats()
        total = stats.get('total_vector_count', 0)
        status['pinecone'] = {
            'ok': True,
            'msg': f'متصل ✓ — Index: {settings.PINECONE_INDEX_NAME}',
            'vector_count': total,
        }
    except Exception as e:
        status['pinecone'] = {'ok': False, 'msg': str(e)[:120], 'vector_count': 0}

    # اختبار بحث
    test_q = request.GET.get('q', '')
    if test_q and status['openai']['ok'] and status['pinecone']['ok']:
        try:
            from .rag_utils import search_similar_chunks
            results = search_similar_chunks(test_q, top_k=5)
            status['test_query'] = {
                'query':   test_q,
                'results': results,
                'count':   len(results),
            }
        except Exception as e:
            status['test_query'] = {'query': test_q, 'error': str(e), 'count': 0}

    return render(request, 'chatapp/admin_rag_status.html', {'status': status})
    last_30_days = timezone.now() - timedelta(days=30)
    lawyers_by_specialization = LawyerProfile.objects.values('specialization').annotate(count=Count('id')).order_by('-count')
    top_lawyers = LawyerProfile.objects.filter(is_verified=True).order_by('-rating', '-total_reviews')[:10]
    consultations_by_status = Consultation.objects.values('status').annotate(count=Count('id'))
    recent_activity = {
        'new_users': User.objects.filter(date_joined__gte=last_30_days).count(),
        'new_lawyers': LawyerProfile.objects.filter(created_at__gte=last_30_days).count(),
        'new_consultations': Consultation.objects.filter(created_at__gte=last_30_days).count(),
        'new_feedbacks': Feedback.objects.filter(created_at__gte=last_30_days).count(),
    }
    return render(request, 'chatapp/admin_statistics.html', {
        'lawyers_by_specialization': lawyers_by_specialization,
        'top_lawyers': top_lawyers,
        'consultations_by_status': consultations_by_status,
        'recent_activity': recent_activity,
    })


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