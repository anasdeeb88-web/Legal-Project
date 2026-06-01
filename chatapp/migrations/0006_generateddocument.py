from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('chatapp', '0005_officialdocumentcategory_color'),
    ]

    operations = [
        migrations.CreateModel(
            name='GeneratedDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('doc_type', models.CharField(
                    choices=[
                        ('sale_property', 'عقد بيع عقار'),
                        ('sale_vehicle', 'عقد بيع سيارة'),
                        ('sale_goods', 'عقد بيع بضاعة'),
                        ('rent_residential', 'عقد إيجار سكني'),
                        ('rent_commercial', 'عقد إيجار تجاري'),
                        ('employment', 'عقد عمل'),
                        ('services', 'عقد تقديم خدمات'),
                        ('contractor', 'عقد مقاولة'),
                        ('loan', 'عقد قرض مالي'),
                        ('mortgage', 'سند رهن عقاري'),
                        ('partnership', 'عقد شراكة تجارية'),
                        ('power_of_attorney', 'وكالة قانونية عامة'),
                        ('power_of_attorney_special', 'وكالة خاصة'),
                        ('inheritance_acknowledgment', 'إقرار بالإرث'),
                        ('debt_acknowledgment', 'إقرار بالدين'),
                        ('court_settlement', 'صلح قضائي / تسوية'),
                        ('agency_commercial', 'عقد وكالة تجارية'),
                        ('nda', 'اتفاقية سرية NDA'),
                        ('supply', 'عقد توريد'),
                    ],
                    max_length=60,
                    verbose_name='نوع الوثيقة',
                )),
                ('title', models.CharField(blank=True, max_length=220, verbose_name='العنوان')),
                ('html_content', models.TextField(verbose_name='محتوى HTML')),
                ('form_data', models.JSONField(blank=True, default=dict, verbose_name='بيانات النموذج')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='تاريخ التعديل')),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='generated_documents',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='المستخدم',
                )),
            ],
            options={
                'verbose_name': 'وثيقة منشأة',
                'verbose_name_plural': 'الوثائق المنشأة',
                'ordering': ['-created_at'],
            },
        ),
    ]
