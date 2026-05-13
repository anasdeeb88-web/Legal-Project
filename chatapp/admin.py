from django.contrib import admin
from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "uploaded_at")
    readonly_fields = ("extracted_text",)
    search_fields = ("title", "extracted_text")
    list_filter = ("uploaded_at",)