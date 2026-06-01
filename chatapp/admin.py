import logging
from django.contrib import admin
from django.utils.html import format_html
from django.utils.timezone import now
from .models import (
    Document, LegalArticle,
    UserProfile, LawyerProfile, LawyerReview,
    Consultation, Feedback, Message,
    OfficialDocumentCategory, OfficialDocumentItem,
)

logger = logging.getLogger(__name__)


# ======================================================================
#  Document
# ======================================================================

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display  = ("id", "title", "indexed_badge", "articles_count",
                     "pinecone_chunks", "uploaded_by", "uploaded_at")
    list_filter   = ("is_indexed", "uploaded_at")
    search_fields = ("title",)
    readonly_fields = (
        "indexed_badge", "articles_count", "pinecone_chunks",
        "is_indexed", "uploaded_at", "extracted_text_preview",
    )
    fields = (
        "title", "file", "uploaded_by",
        "indexed_badge", "articles_count", "pinecone_chunks", "uploaded_at",
        "extracted_text_preview",
    )
    actions = ["action_reindex", "action_delete_from_pinecone"]
    show_full_result_count = False

    @admin.display(description="مفهرس", ordering="is_indexed")
    def indexed_badge(self, obj):
        if obj.is_indexed:
            return format_html('<span style="color:#22c55e;font-weight:700">OK مفهرس</span>')
        return format_html('<span style="color:#ef4444;font-weight:700">X غير مفهرس</span>')

    @admin.display(description="معاينة النص")
    def extracted_text_preview(self, obj):
        text = obj.extracted_text or ""
        snippet = text[:800] + ("..." if len(text) > 800 else "")
        return format_html(
            '<pre style="white-space:pre-wrap;max-height:200px;overflow:auto;'
            'font-size:12px;direction:rtl">{}</pre>',
            snippet,
        )

    @admin.action(description="اعادة فهرسة (Pinecone + PostgreSQL)")
    def action_reindex(self, request, queryset):
        from .rag_utils import store_document_in_pinecone, index as pinecone_index
        from .views import _extract_text_from_document
        ok = err = 0
        for doc in queryset:
            try:
                text = _extract_text_from_document(doc)
                if not text.strip():
                    self.message_user(request, f"#{doc.id} - النص فارغ", "warning")
                    err += 1
                    continue
                doc.extracted_text = text
                doc.save(update_fields=["extracted_text"])
                try:
                    pinecone_index.delete(filter={"doc_id": str(doc.id)})
                except Exception as e:
                    logger.warning(f"Pinecone delete #{doc.id}: {e}")
                store_document_in_pinecone(doc.id, text, doc_title=doc.title)
                ok += 1
            except Exception as e:
                logger.error(f"reindex admin #{doc.id}: {e}")
                self.message_user(request, f"#{doc.id} - خطأ: {e}", "error")
                err += 1
        if ok:
            self.message_user(request, f"اعيدت فهرسة {ok} وثيقة بنجاح.")

    @admin.action(description="حذف من Pinecone فقط (دون حذف الوثيقة)")
    def action_delete_from_pinecone(self, request, queryset):
        from .rag_utils import index as pinecone_index
        ok = 0
        for doc in queryset:
            try:
                pinecone_index.delete(filter={"doc_id": str(doc.id)})
                doc.is_indexed      = False
                doc.pinecone_chunks = 0
                doc.save(update_fields=["is_indexed", "pinecone_chunks"])
                ok += 1
            except Exception as e:
                self.message_user(request, f"#{doc.id} - خطأ: {e}", "error")
        if ok:
            self.message_user(request, f"حذفت vectors {ok} وثيقة من Pinecone.")


# ======================================================================
#  LegalArticle
# ======================================================================

@admin.register(LegalArticle)
class LegalArticleAdmin(admin.ModelAdmin):
    list_display  = ("article_number", "article_number_display",
                     "doc_link", "section_path", "text_preview", "order_in_doc")
    list_filter   = ("doc",)
    search_fields = ("article_number_display", "text", "section_path")
    raw_id_fields = ("doc",)
    ordering      = ("doc", "order_in_doc")
    readonly_fields = ("doc", "article_number", "article_number_display",
                       "section_path", "order_in_doc", "text")
    show_full_result_count = False

    @admin.display(description="الوثيقة")
    def doc_link(self, obj):
        return format_html(
            '<a href="/admin/chatapp/document/{}/change/">{}</a>',
            obj.doc_id, obj.doc.title[:40],
        )

    @admin.display(description="معاينة النص")
    def text_preview(self, obj):
        return (obj.text[:100] + "...") if len(obj.text) > 100 else obj.text

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ======================================================================
#  UserProfile
# ======================================================================

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ("user", "user_type", "city", "phone", "created_at")
    list_filter   = ("user_type", "city")
    search_fields = ("user__username", "user__email", "phone")
    raw_id_fields = ("user",)


# ======================================================================
#  LawyerProfile
# ======================================================================

@admin.register(LawyerProfile)
class LawyerProfileAdmin(admin.ModelAdmin):
    list_display  = ("full_name", "specialization", "address_preview",
                     "rating", "total_reviews", "is_verified", "is_available", "created_at")
    list_filter   = ("is_verified", "is_available", "specialization")
    search_fields = ("user__username", "user__first_name", "user__last_name",
                     "license_number", "office_name")
    raw_id_fields = ("user",)
    actions       = ["action_verify", "action_unverify",
                     "action_set_available", "action_set_unavailable"]
    readonly_fields = ("rating", "total_reviews", "created_at", "updated_at")

    @admin.display(description="الاسم الكامل")
    def full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description="العنوان")
    def address_preview(self, obj):
        return (obj.office_address or "").split("\n")[0][:40]

    @admin.action(description="تفعيل التحقق")
    def action_verify(self, request, queryset):
        n = queryset.update(is_verified=True)
        self.message_user(request, f"تم التحقق من {n} محامٍ.")

    @admin.action(description="الغاء التحقق")
    def action_unverify(self, request, queryset):
        n = queryset.update(is_verified=False)
        self.message_user(request, f"الغي التحقق من {n} محامٍ.")

    @admin.action(description="تعيين متاح")
    def action_set_available(self, request, queryset):
        n = queryset.update(is_available=True)
        self.message_user(request, f"{n} محامٍ اصبح متاحاً.")

    @admin.action(description="تعيين غير متاح")
    def action_set_unavailable(self, request, queryset):
        n = queryset.update(is_available=False)
        self.message_user(request, f"{n} محامٍ اصبح غير متاح.")


# ======================================================================
#  LawyerReview
# ======================================================================

@admin.register(LawyerReview)
class LawyerReviewAdmin(admin.ModelAdmin):
    list_display  = ("lawyer", "user", "rating", "comment_preview", "created_at")
    list_filter   = ("rating",)
    search_fields = ("lawyer__user__username", "user__username", "comment")
    raw_id_fields = ("lawyer", "user")
    readonly_fields = ("created_at",)

    @admin.display(description="التعليق")
    def comment_preview(self, obj):
        return (obj.comment[:80] + "...") if len(obj.comment) > 80 else obj.comment


# ======================================================================
#  Consultation
# ======================================================================

@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display  = ("title", "user", "lawyer", "status_badge",
                     "created_at", "response_at")
    list_filter   = ("status", "created_at")
    search_fields = ("title", "description", "user__username", "lawyer__username")
    raw_id_fields = ("user", "lawyer")
    readonly_fields = ("created_at", "updated_at", "response_at")
    actions = ["action_accept", "action_reject", "action_complete"]

    @admin.display(description="الحالة", ordering="status")
    def status_badge(self, obj):
        colors = {
            "pending":   ("#f59e0b", "قيد الانتظار"),
            "accepted":  ("#3b82f6", "مقبول"),
            "rejected":  ("#ef4444", "مرفوض"),
            "completed": ("#22c55e", "مكتمل"),
            "cancelled": ("#6b7280", "ملغي"),
        }
        color, label = colors.get(obj.status, ("#6b7280", obj.status))
        return format_html(
            '<span style="color:{};font-weight:700">{}</span>', color, label
        )

    @admin.action(description="قبول الاستشارات المحددة")
    def action_accept(self, request, queryset):
        n = queryset.filter(status="pending").update(status="accepted")
        self.message_user(request, f"قبلت {n} استشارة.")

    @admin.action(description="رفض الاستشارات المحددة")
    def action_reject(self, request, queryset):
        n = queryset.exclude(status="completed").update(status="rejected")
        self.message_user(request, f"رفضت {n} استشارة.")

    @admin.action(description="تعيين مكتملة")
    def action_complete(self, request, queryset):
        n = queryset.filter(status="accepted").update(
            status="completed", response_at=now()
        )
        self.message_user(request, f"اكتملت {n} استشارة.")


# ======================================================================
#  Feedback
# ======================================================================

@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display  = ("subject", "user", "feedback_type",
                     "is_read", "is_resolved", "created_at")
    list_filter   = ("feedback_type", "is_read", "is_resolved", "created_at")
    search_fields = ("subject", "message", "user__username")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "resolved_at")
    actions = ["action_mark_read", "action_mark_resolved"]

    @admin.action(description="تعيين مقروءة")
    def action_mark_read(self, request, queryset):
        n = queryset.update(is_read=True)
        self.message_user(request, f"{n} تغذية راجعة معلمة كمقروءة.")

    @admin.action(description="تعيين محلولة")
    def action_mark_resolved(self, request, queryset):
        n = queryset.update(is_resolved=True, resolved_at=now())
        self.message_user(request, f"{n} تغذية راجعة معلمة كمحلولة.")


# ======================================================================
#  Message
# ======================================================================

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display  = ("subject", "sender", "recipient", "is_read", "created_at")
    list_filter   = ("is_read", "created_at")
    search_fields = ("subject", "body", "sender__username", "recipient__username")
    raw_id_fields = ("sender", "recipient")
    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        return False


# ======================================================================
#  Official Documents
# ======================================================================

class OfficialDocumentItemInline(admin.TabularInline):
    model       = OfficialDocumentItem
    extra       = 1
    fields      = ('name', 'description', 'is_required', 'order')
    ordering    = ('order', 'name')


@admin.register(OfficialDocumentCategory)
class OfficialDocumentCategoryAdmin(admin.ModelAdmin):
    list_display  = ('icon', 'name', 'items_count_display', 'order', 'is_active', 'created_at')
    list_editable = ('order', 'is_active')
    list_filter   = ('is_active',)
    search_fields = ('name', 'description')
    inlines       = [OfficialDocumentItemInline]

    @admin.display(description="عدد الأوراق")
    def items_count_display(self, obj):
        count = obj.items.count()
        return format_html(
            '<span style="font-weight:700;color:#3b82f6">{}</span>', count
        )


@admin.register(OfficialDocumentItem)
class OfficialDocumentItemAdmin(admin.ModelAdmin):
    list_display  = ('name', 'category', 'required_badge', 'order')
    list_filter   = ('category', 'is_required')
    search_fields = ('name', 'description', 'category__name')
    list_editable = ('order',)

    @admin.display(description="مطلوب")
    def required_badge(self, obj):
        if obj.is_required:
            return format_html('<span style="color:#22c55e;font-weight:700">✔ مطلوب</span>')
        return format_html('<span style="color:#6b7280">اختياري</span>')
