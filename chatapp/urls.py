from django.urls import path
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate, login as auth_login
from django.shortcuts import redirect, render
from . import views


def custom_login(request):
    """تسجيل دخول المستخدمين العاديين فقط"""
    if request.user.is_authenticated:
        return views.smart_redirect(request.user)

    error = False
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user     = authenticate(request, username=username, password=password)

        if user is not None:
            if views.is_lawyer(user) and not views.is_admin(user):
                error = 'lawyer_account'
            else:
                auth_login(request, user)
                return views.smart_redirect(user)
        else:
            error = True

    return render(request, 'login.html', {'error': error})


urlpatterns = [
    # ── الصفحة الرئيسية ──
    path("",               views.landing,              name='landing'),

    # ── المصادقة ──
    path("login/",               custom_login,                name='login'),
    path("password/forgot/",     views.password_forgot,       name="password_forgot"),
    path("password/verify/",     views.verify_reset_code,     name="verify_reset_code"),
    path("password/reset/",      views.reset_password,        name="reset_password"),
    path("register/",            views.register,              name="register"),
    path("lawyer/login/",     views.lawyer_login,        name="lawyer_login"),
    path("lawyer/register/", views.lawyer_register,    name="lawyer_register"),
    path("lawyer/pending/",  views.lawyer_pending,     name="lawyer_pending"),
    path("logout/", auth_views.LogoutView.as_view(next_page='/'), name="logout"),

    # ── الصفحات الأساسية ──
    path("index/",              views.index,               name="index"),
    path("chat/",               views.chat,                name="chat"),
    path("chat-new/",           views.chat_new,            name="chat_new"),
    path("official-documents/", views.official_documents,  name="official_documents"),
    path("legal-documents/",    views.legal_documents,     name="legal_documents"),

    # ── الوثائق ──
    path("upload/",                              views.upload_document,  name="upload"),
    path("documents/<int:doc_id>/delete/",       views.delete_document,  name="delete_document"),
    path("documents/<int:doc_id>/reindex/",      views.reindex_document, name="reindex_document"),  # ← جديد

    # ── الدردشة مع RAG ──
    path("chat/send/", views.chat_send, name="chat_send"),

    # ── دليل المحامين ──
    path("lawyers/",                          views.lawyers_list,          name="lawyers_list"),
    path("lawyers/map/",                      views.lawyers_map,           name="lawyers_map"),
    path("lawyers/<int:lawyer_id>/",          views.lawyer_detail,         name="lawyer_detail"),
    path("lawyers/<int:lawyer_id>/review/",   views.submit_lawyer_review,  name="submit_review"),
    path("lawyers/<int:lawyer_id>/consult/",  views.request_consultation,  name="request_consultation"),

    # ── الاستشارات ──
    path("consultations/",                       views.my_consultations,    name="my_consultations"),
    path("consultations/<int:consultation_id>/", views.consultation_detail, name="consultation_detail"),

    # ── التغذية الراجعة ──
    path("feedback/", views.submit_feedback, name="submit_feedback"),

    # ── لوحة تحكم المحامي ──
    path("lawyer/dashboard/",                                       views.lawyer_dashboard,         name="lawyer_dashboard"),
    path("lawyer/consultations/",                                    views.lawyer_consultations,     name="lawyer_consultations"),
    path("lawyer/consultations/<int:consultation_id>/respond/",     views.respond_consultation,     name="respond_consultation"),
    path("lawyer/profile/edit/",                                    views.lawyer_profile_edit,      name="lawyer_profile_edit"),
    path("lawyer/my-profile/",                                      views.lawyer_my_public_profile, name="lawyer_my_public_profile"),
    path("lawyer/feedback/",                                        views.lawyer_feedback_to_admin, name="lawyer_feedback_to_admin"),

    # ── لوحة تحكم المدير ──
    path("admin-panel/dashboard/",                      views.admin_dashboard,         name="admin_dashboard"),
    path("admin-panel/lawyers/",                         views.admin_lawyers_management,name="admin_lawyers"),
    path("admin-panel/lawyers/<int:lawyer_id>/edit/",   views.admin_lawyer_edit,       name="admin_lawyer_edit"),
    path("admin-panel/lawyers/<int:lawyer_id>/verify/", views.admin_verify_lawyer,     name="admin_verify_lawyer"),
    path("admin-panel/feedbacks/",                       views.admin_feedbacks,         name="admin_feedbacks"),
    path("admin-panel/feedbacks/<int:feedback_id>/",    views.admin_feedback_detail,   name="admin_feedback_detail"),
    path("admin-panel/documents/",                       views.admin_documents,         name="admin_documents"),
    path("admin-panel/rag-status/",                     views.admin_rag_status,        name="admin_rag_status"),
    path("admin-panel/statistics/",                     views.admin_statistics,        name="admin_statistics"),

    # ── الوثائق الرسمية (إدارة) ──
    path("admin-panel/official-docs/",                               views.admin_official_docs,           name="admin_official_docs"),
    path("admin-panel/official-docs/category/add/",                  views.admin_official_doc_cat_add,    name="admin_official_doc_cat_add"),
    path("admin-panel/official-docs/category/<int:cat_id>/edit/",    views.admin_official_doc_cat_edit,   name="admin_official_doc_cat_edit"),
    path("admin-panel/official-docs/category/<int:cat_id>/delete/",  views.admin_official_doc_cat_delete, name="admin_official_doc_cat_delete"),
    path("admin-panel/official-docs/item/add/",                      views.admin_official_doc_item_add,   name="admin_official_doc_item_add"),
    path("admin-panel/official-docs/item/<int:item_id>/edit/",       views.admin_official_doc_item_edit,  name="admin_official_doc_item_edit"),
    path("admin-panel/official-docs/item/<int:item_id>/delete/",     views.admin_official_doc_item_delete,name="admin_official_doc_item_delete"),

    # ── منشئ الوثائق القانونية (إدارة) ──
    path("admin-panel/legal-docs/",                                   views.admin_legal_docs,              name="admin_legal_docs"),
    path("admin-panel/legal-docs/type/<int:type_id>/save/",           views.admin_legal_doc_type_save,     name="admin_legal_doc_type_save"),
    path("admin-panel/legal-docs/type/<int:type_id>/toggle/",         views.admin_legal_doc_type_toggle,   name="admin_legal_doc_type_toggle"),
    path("admin-panel/legal-docs/generated/<int:doc_id>/",            views.admin_generated_doc_view,      name="admin_generated_doc_view"),
    path("admin-panel/legal-docs/generated/<int:doc_id>/delete/",     views.admin_generated_doc_delete,    name="admin_generated_doc_delete"),

    # ── JSON APIs ──
    path("api/lawyers/",                views.lawyers_list_json,  name="lawyers_list_json"),
    path("api/lawyers/<int:lawyer_id>/", views.lawyer_detail_json, name="lawyer_detail_json"),

    # ── منشئ الوثائق — API ──
    path("api/documents/save/",                views.save_generated_document,   name="save_generated_document"),
    path("api/documents/<int:doc_id>/",        views.load_generated_document,   name="load_generated_document"),
    path("api/documents/<int:doc_id>/delete/", views.delete_generated_document, name="delete_generated_document"),
]