from django.urls import path
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate, login as auth_login
from django.shortcuts import redirect, render
from . import views


# ===== Custom Login — يوجه حسب role المرسلة في POST =====
def custom_login(request):
    if request.user.is_authenticated:
        return views.smart_redirect(request.user)

    form = AuthenticationForm(request)
    error = False

    if request.method == 'POST':
        role = request.POST.get('role', 'user')  # 'user' أو 'lawyer'
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            # تحقق من تطابق الدور
            if role == 'lawyer' and not views.is_lawyer(user):
                # حساب مستخدم عادي حاول يدخل كمحامٍ
                form = AuthenticationForm(request, data=request.POST)
                error = 'not_lawyer'
            elif role == 'user' and views.is_lawyer(user) and not views.is_admin(user):
                # محامٍ حاول يدخل كمستخدم — بنوجهه صح على أي حال
                auth_login(request, user)
                return views.smart_redirect(user)
            else:
                auth_login(request, user)
                return views.smart_redirect(user)
        else:
            form = AuthenticationForm(request, data=request.POST)
            error = True

    return render(request, 'login.html', {'form': form, 'error': error})


urlpatterns = [
    # ==================== المصادقة ====================
    path("", custom_login, name='login'),
    path("login/", custom_login, name='login_alt'),
    path("register/", views.register, name="register"),
    path("lawyer/register/", views.lawyer_register, name="lawyer_register"),
    path("lawyer/pending/", views.lawyer_pending, name="lawyer_pending"),
    path("logout/", auth_views.LogoutView.as_view(next_page='/'), name="logout"),

    # ==================== الصفحات الأساسية ====================
    path("index/", views.index, name="index"),
    path("chat/", views.chat, name="chat"),
    path("chat-new/", views.chat_new, name="chat_new"),

    # ==================== الوثائق ====================
    path("upload/", views.upload_document, name="upload"),
    path("documents/<int:doc_id>/delete/", views.delete_document, name="delete_document"),

    # ==================== الدردشة مع RAG ====================
    path("chat/send/", views.chat_send, name="chat_send"),

    # ==================== دليل المحامين ====================
    path("lawyers/", views.lawyers_list, name="lawyers_list"),
    path("lawyers/map/", views.lawyers_map, name="lawyers_map"),
    path("lawyers/<int:lawyer_id>/", views.lawyer_detail, name="lawyer_detail"),
    path("lawyers/<int:lawyer_id>/review/", views.submit_lawyer_review, name="submit_review"),
    path("lawyers/<int:lawyer_id>/consult/", views.request_consultation, name="request_consultation"),

    # ==================== الاستشارات ====================
    path("consultations/", views.my_consultations, name="my_consultations"),
    path("consultations/<int:consultation_id>/", views.consultation_detail, name="consultation_detail"),

    # ==================== التغذية الراجعة ====================
    path("feedback/", views.submit_feedback, name="submit_feedback"),

    # ==================== لوحة تحكم المحامي ====================
    path("lawyer/dashboard/", views.lawyer_dashboard, name="lawyer_dashboard"),
    path("lawyer/consultations/", views.lawyer_consultations, name="lawyer_consultations"),
    path("lawyer/consultations/<int:consultation_id>/respond/", views.respond_consultation, name="respond_consultation"),
    path("lawyer/profile/edit/", views.lawyer_profile_edit, name="lawyer_profile_edit"),
    path("lawyer/feedback/", views.lawyer_feedback_to_admin, name="lawyer_feedback_to_admin"),

    # ==================== لوحة تحكم المدير ====================
    path("admin-panel/dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-panel/lawyers/", views.admin_lawyers_management, name="admin_lawyers"),
    path("admin-panel/lawyers/<int:lawyer_id>/edit/", views.admin_lawyer_edit, name="admin_lawyer_edit"),
    path("admin-panel/lawyers/<int:lawyer_id>/verify/", views.admin_verify_lawyer, name="admin_verify_lawyer"),
    path("admin-panel/feedbacks/", views.admin_feedbacks, name="admin_feedbacks"),
    path("admin-panel/feedbacks/<int:feedback_id>/", views.admin_feedback_detail, name="admin_feedback_detail"),
    path("admin-panel/documents/", views.admin_documents, name="admin_documents"),
    path("admin-panel/rag-status/", views.admin_rag_status, name="admin_rag_status"),
    path("admin-panel/statistics/", views.admin_statistics, name="admin_statistics"),

    # ==================== JSON APIs ====================
    path("api/lawyers/", views.lawyers_list_json, name="lawyers_list_json"),
    path("api/lawyers/<int:lawyer_id>/", views.lawyer_detail_json, name="lawyer_detail_json"),
]