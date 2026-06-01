from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class UserProfile(models.Model):
    USER_TYPES = (('user','مستخدم عادي'),('lawyer','محامي'),('admin','مدير'))
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='user')
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "ملف تعريف المستخدم"
        verbose_name_plural = "ملفات تعريف المستخدمين"
    def __str__(self):
        return f"{self.user.username} - {self.get_user_type_display()}"


class LawyerProfile(models.Model):
    SPECIALIZATIONS = (
        ('criminal','جنائي'),('civil','مدني'),('commercial','تجاري'),
        ('family','أحوال شخصية'),('administrative','إداري'),('labor','عمل'),
        ('real_estate','عقاري'),('intellectual','ملكية فكرية'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='lawyer_profile')
    license_number = models.CharField(max_length=50, unique=True)
    specialization = models.CharField(max_length=20, choices=SPECIALIZATIONS)
    experience_years = models.PositiveIntegerField(default=0)
    office_name = models.CharField(max_length=200, blank=True)
    office_address = models.TextField()
    office_phone  = models.CharField(max_length=20)
    mobile_phone  = models.CharField(max_length=20, blank=True, default='', verbose_name='رقم الموبايل')
    office_email  = models.EmailField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    languages = models.CharField(max_length=200, default="العربية")
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0,
                                  validators=[MinValueValidator(0), MaxValueValidator(5)])
    total_reviews = models.PositiveIntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "ملف محامي"
        verbose_name_plural = "ملفات المحامين"
        ordering = ['-rating', '-created_at']
    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.get_specialization_display()}"
    def update_rating(self):
        reviews = self.reviews.all()
        if reviews.exists():
            self.rating = sum(r.rating for r in reviews) / reviews.count()
            self.total_reviews = reviews.count()
            self.save()


class Document(models.Model):
    """وثيقة قانونية — تُفهرس في Pinecone (دلالي) و LegalArticle (بنيوي)"""
    title          = models.CharField(max_length=255, verbose_name="العنوان")
    uploaded_by    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at    = models.DateTimeField(auto_now_add=True)
    file           = models.FileField(upload_to="documents/")
    extracted_text = models.TextField(blank=True)

    # ── إحصائيات الفهرسة ──
    articles_count  = models.PositiveIntegerField(default=0, verbose_name="عدد المواد المفهرسة")
    pinecone_chunks = models.PositiveIntegerField(default=0, verbose_name="مقاطع Pinecone")
    is_indexed      = models.BooleanField(default=False, verbose_name="مفهرس")

    class Meta:
        verbose_name = "وثيقة"
        verbose_name_plural = "الوثائق"
        ordering = ['-uploaded_at']
    def __str__(self):
        return f"{self.title} ({self.id})"


class LegalArticle(models.Model):
    """
    مادة قانونية واحدة — تُستخدم في Structured Retrieval.

    البحث: WHERE article_number = 233          (ARTICLE_EXACT)
            WHERE article_number BETWEEN 10 AND 15  (ARTICLE_RANGE)
            WHERE text ILIKE '%الطلاق%'         (KEYWORD/TOPIC)
    """
    doc = models.ForeignKey(
        Document, on_delete=models.CASCADE,
        related_name='articles', db_index=True,
    )
    # الرقم الصافي للفلترة السريعة
    article_number = models.PositiveIntegerField(db_index=True)
    # النص كما يظهر في الوثيقة: "مادة 233" أو "المادة الأولى"
    article_number_display = models.CharField(max_length=60)
    # التسلسل الهرمي: الكتاب > الباب > الفصل
    section_path = models.CharField(max_length=500, blank=True, db_index=True)
    # النص الكامل للمادة
    text = models.TextField()
    # ترتيب الظهور في الوثيقة
    order_in_doc = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        verbose_name = "مادة قانونية"
        verbose_name_plural = "المواد القانونية"
        unique_together = [('doc', 'article_number')]
        ordering = ['doc', 'order_in_doc']
        indexes = [
            models.Index(fields=['doc', 'article_number'], name='idx_doc_artnum'),
            models.Index(fields=['section_path'],           name='idx_section_path'),
        ]
    def __str__(self):
        return f"{self.doc.title} — {self.article_number_display}"

    @property
    def header(self):
        if self.section_path and self.section_path != 'عام':
            return f"{self.section_path} > {self.article_number_display}"
        return f"{self.doc.title} — {self.article_number_display}"

    def to_rag_chunk(self):
        """يحوّل المادة إلى صيغة chunk موحّدة متوافقة مع نتائج Pinecone."""
        return {
            "text":       f"{self.article_number_display}\n{self.text}",
            "doc_title":  self.doc.title,
            "doc_id":     self.doc_id,
            "header":     self.header,
            "articles":   self.article_number_display,
            "art_nums":   [str(self.article_number)],
            "section_path": self.section_path,
            "type":       "atom",
            "source":     "postgresql",
            "pg_rank":    1.0,
        }


class Consultation(models.Model):
    STATUS_CHOICES = (
        ('pending','قيد الانتظار'),('accepted','مقبول'),
        ('rejected','مرفوض'),('completed','مكتمل'),('cancelled','ملغي'),
    )
    user   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='consultations')
    lawyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lawyer_consultations')
    title       = models.CharField(max_length=200)
    description = models.TextField()
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    audio_file          = models.FileField(upload_to='consultations/audio/', blank=True, null=True)
    audio_transcription = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    response    = models.TextField(blank=True)
    response_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        verbose_name = "استشارة"
        verbose_name_plural = "الاستشارات"
        ordering = ['-created_at']
    def __str__(self):
        return f"{self.title} - {self.user.username} → {self.lawyer.username}"


class LawyerReview(models.Model):
    lawyer     = models.ForeignKey(LawyerProfile, on_delete=models.CASCADE, related_name='reviews')
    user       = models.ForeignKey(User, on_delete=models.CASCADE)
    rating     = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "تقييم محامي"
        verbose_name_plural = "تقييمات المحامين"
        unique_together = ['lawyer', 'user']
        ordering = ['-created_at']
    def __str__(self):
        return f"{self.user.username} → {self.lawyer.user.username}: {self.rating}★"
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.lawyer.update_rating()


class Feedback(models.Model):
    FEEDBACK_TYPES = (
        ('bug','مشكلة تقنية'),('suggestion','اقتراح'),
        ('complaint','شكوى'),('other','أخرى'),
    )
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedbacks')
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPES, default='suggestion')
    subject       = models.CharField(max_length=200)
    message       = models.TextField()
    audio_file          = models.FileField(upload_to='feedback/audio/', blank=True, null=True)
    audio_transcription = models.TextField(blank=True)
    is_read      = models.BooleanField(default=False)
    is_resolved  = models.BooleanField(default=False)
    admin_response = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    resolved_at  = models.DateTimeField(null=True, blank=True)
    class Meta:
        verbose_name = "تغذية راجعة"
        verbose_name_plural = "التغذية الراجعة"
        ordering = ['-created_at']
    def __str__(self):
        return f"{self.subject} - {self.user.username}"


class Message(models.Model):
    sender    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    subject   = models.CharField(max_length=200, blank=True)
    body      = models.TextField()
    is_read   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "رسالة"
        verbose_name_plural = "الرسائل"
        ordering = ['-created_at']
    def __str__(self):
        return f"{self.sender.username} → {self.recipient.username}"


class OfficialDocumentCategory(models.Model):
    """تصنيف وثيقة رسمية — يُعرض في قسم الأوراق الرسمية بالصفحة الرئيسية"""
    name        = models.CharField(max_length=200, verbose_name="اسم الوثيقة")
    icon        = models.CharField(max_length=10,  default='📋', verbose_name="الأيقونة")
    color       = models.CharField(max_length=200, default='linear-gradient(135deg,#0b1628,#b8965a)', verbose_name="اللون / التدرج")
    description = models.TextField(blank=True, verbose_name="وصف الوثيقة")
    order       = models.PositiveIntegerField(default=0, verbose_name="الترتيب")
    is_active   = models.BooleanField(default=True, verbose_name="نشط")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "تصنيف وثيقة رسمية"
        verbose_name_plural = "تصنيفات الوثائق الرسمية"
        ordering            = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def items_count(self):
        return self.items.count()


class OfficialDocumentItem(models.Model):
    """ورقة فردية مطلوبة ضمن وثيقة رسمية"""
    category    = models.ForeignKey(
        OfficialDocumentCategory, on_delete=models.CASCADE,
        related_name='items', verbose_name="التصنيف"
    )
    name        = models.TextField(verbose_name="نص البند")
    description = models.TextField(blank=True, verbose_name="التفاصيل والملاحظات")
    is_required = models.BooleanField(default=True, verbose_name="مطلوب")
    order       = models.PositiveIntegerField(default=0, verbose_name="الترتيب")

    class Meta:
        verbose_name        = "ورقة رسمية"
        verbose_name_plural = "الأوراق الرسمية"
        ordering            = ['order', 'name']

    def __str__(self):
        return f"{self.category.name} — {self.name}"

class GeneratedDocument(models.Model):
    DOC_TYPES = [
        ('sale_property',              'عقد بيع عقار'),
        ('sale_vehicle',               'عقد بيع سيارة'),
        ('sale_goods',                 'عقد بيع بضاعة'),
        ('rent_residential',           'عقد إيجار سكني'),
        ('rent_commercial',            'عقد إيجار تجاري'),
        ('employment',                 'عقد عمل'),
        ('services',                   'عقد تقديم خدمات'),
        ('contractor',                 'عقد مقاولة'),
        ('loan',                       'عقد قرض مالي'),
        ('mortgage',                   'سند رهن عقاري'),
        ('partnership',                'عقد شراكة تجارية'),
        ('power_of_attorney',          'وكالة قانونية عامة'),
        ('power_of_attorney_special',  'وكالة خاصة'),
        ('inheritance_acknowledgment', 'إقرار بالإرث'),
        ('debt_acknowledgment',        'إقرار بالدين'),
        ('court_settlement',           'صلح قضائي / تسوية'),
        ('agency_commercial',          'عقد وكالة تجارية'),
        ('nda',                        'اتفاقية سرية NDA'),
        ('supply',                     'عقد توريد'),
    ]

    user         = models.ForeignKey(User, on_delete=models.CASCADE,
                                     related_name='generated_documents',
                                     verbose_name='المستخدم')
    doc_type     = models.CharField(max_length=60, choices=DOC_TYPES, verbose_name='نوع الوثيقة')
    title        = models.CharField(max_length=220, blank=True, verbose_name='العنوان')
    html_content = models.TextField(verbose_name='محتوى HTML')
    form_data    = models.JSONField(default=dict, blank=True, verbose_name='بيانات النموذج')
    created_at   = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at   = models.DateTimeField(auto_now=True,     verbose_name='تاريخ التعديل')

    DOC_ICONS = {
        'sale_property': '🏠', 'sale_vehicle': '🚗', 'sale_goods': '📦',
        'rent_residential': '🏡', 'rent_commercial': '🏢', 'employment': '💼',
        'services': '🔧', 'contractor': '🏗️', 'loan': '💰', 'mortgage': '🏦',
        'partnership': '🤝', 'power_of_attorney': '📜', 'power_of_attorney_special': '📋',
        'inheritance_acknowledgment': '⚖️', 'debt_acknowledgment': '💳',
        'court_settlement': '🔨', 'agency_commercial': '🏪', 'nda': '🔒', 'supply': '🚚',
    }

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'وثيقة منشأة'
        verbose_name_plural = 'الوثائق المنشأة'

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.user.username}"

    @property
    def icon(self):
        return self.DOC_ICONS.get(self.doc_type, '📄')


class LegalDocumentType(models.Model):
    """نوع وثيقة قانونية — يُدار من لوحة الإدارة"""
    slug        = models.CharField(max_length=60, unique=True, verbose_name='المعرّف')
    name        = models.CharField(max_length=200, verbose_name='الاسم')
    icon        = models.CharField(max_length=10, default='📄', verbose_name='الأيقونة')
    description = models.TextField(blank=True, verbose_name='الوصف')
    is_active   = models.BooleanField(default=True, verbose_name='مفعّل')
    order       = models.PositiveIntegerField(default=0, verbose_name='الترتيب')

    class Meta:
        ordering            = ['order', 'name']
        verbose_name        = 'نوع وثيقة قانونية'
        verbose_name_plural = 'أنواع الوثائق القانونية'

    def __str__(self):
        return self.name
