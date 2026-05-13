from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class UserProfile(models.Model):
    """ملف تعريف المستخدم الموسع"""
    USER_TYPES = (
        ('user', 'مستخدم عادي'),
        ('lawyer', 'محامي'),
        ('admin', 'مدير'),
    )
    
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
    """معلومات المحامي التفصيلية"""
    SPECIALIZATIONS = (
        ('criminal', 'جنائي'),
        ('civil', 'مدني'),
        ('commercial', 'تجاري'),
        ('family', 'أحوال شخصية'),
        ('administrative', 'إداري'),
        ('labor', 'عمل'),
        ('real_estate', 'عقاري'),
        ('intellectual', 'ملكية فكرية'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='lawyer_profile')
    license_number = models.CharField(max_length=50, unique=True)
    specialization = models.CharField(max_length=20, choices=SPECIALIZATIONS)
    experience_years = models.PositiveIntegerField(default=0)
    
    # معلومات المكتب
    office_name = models.CharField(max_length=200, blank=True)
    office_address = models.TextField()
    office_phone = models.CharField(max_length=20)
    office_email = models.EmailField()
    
    # موقع جغرافي (Google Maps)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # معلومات إضافية
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    languages = models.CharField(max_length=200, default="العربية")
    
    # التقييمات
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0, 
                                  validators=[MinValueValidator(0), MaxValueValidator(5)])
    total_reviews = models.PositiveIntegerField(default=0)
    
    # الحالة
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
        """تحديث التقييم بناءً على المراجعات"""
        reviews = self.reviews.all()
        if reviews.exists():
            total = sum([r.rating for r in reviews])
            self.rating = total / reviews.count()
            self.total_reviews = reviews.count()
            self.save()


class Document(models.Model):
    """الوثائق القانونية المرفوعة"""
    title = models.CharField(max_length=255, verbose_name="العنوان")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الرفع")
    file = models.FileField(upload_to="documents/", verbose_name="الملف")
    extracted_text = models.TextField(blank=True, verbose_name="النص المستخرج")
    
    class Meta:
        verbose_name = "وثيقة"
        verbose_name_plural = "الوثائق"
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.title} ({self.id})"


class Consultation(models.Model):
    """طلبات الاستشارة"""
    STATUS_CHOICES = (
        ('pending', 'قيد الانتظار'),
        ('accepted', 'مقبول'),
        ('rejected', 'مرفوض'),
        ('completed', 'مكتمل'),
        ('cancelled', 'ملغي'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='consultations')
    lawyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lawyer_consultations')
    
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # ملف صوتي اختياري
    audio_file = models.FileField(upload_to='consultations/audio/', blank=True, null=True)
    audio_transcription = models.TextField(blank=True)  # النص المستخرج من الصوت
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    response = models.TextField(blank=True)
    response_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "استشارة"
        verbose_name_plural = "الاستشارات"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.user.username} → {self.lawyer.username}"


class LawyerReview(models.Model):
    """تقييمات المحامين"""
    lawyer = models.ForeignKey(LawyerProfile, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "تقييم محامي"
        verbose_name_plural = "تقييمات المحامين"
        unique_together = ['lawyer', 'user']  # مستخدم واحد يقيم محامي مرة واحدة
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} → {self.lawyer.user.username}: {self.rating}★"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.lawyer.update_rating()


class Feedback(models.Model):
    """ملاحظات وتغذية راجعة للإدارة"""
    FEEDBACK_TYPES = (
        ('bug', 'مشكلة تقنية'),
        ('suggestion', 'اقتراح'),
        ('complaint', 'شكوى'),
        ('other', 'أخرى'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='feedbacks')
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPES, default='suggestion')
    subject = models.CharField(max_length=200)
    message = models.TextField()
    
    # ملف صوتي اختياري
    audio_file = models.FileField(upload_to='feedback/audio/', blank=True, null=True)
    audio_transcription = models.TextField(blank=True)
    
    # حالة المعالجة
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    admin_response = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "تغذية راجعة"
        verbose_name_plural = "التغذية الراجعة"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.subject} - {self.user.username}"


class Message(models.Model):
    """نظام المراسلة"""
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "رسالة"
        verbose_name_plural = "الرسائل"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.sender.username} → {self.recipient.username}"