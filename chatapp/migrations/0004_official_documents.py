from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chatapp', '0003_alter_document_extracted_text_alter_document_file_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='OfficialDocumentCategory',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',        models.CharField(max_length=200, verbose_name='اسم الوثيقة')),
                ('icon',        models.CharField(default='📋', max_length=10, verbose_name='الأيقونة')),
                ('description', models.TextField(blank=True, verbose_name='وصف الوثيقة')),
                ('order',       models.PositiveIntegerField(default=0, verbose_name='الترتيب')),
                ('is_active',   models.BooleanField(default=True, verbose_name='نشط')),
                ('created_at',  models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name':        'تصنيف وثيقة رسمية',
                'verbose_name_plural': 'تصنيفات الوثائق الرسمية',
                'ordering':            ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='OfficialDocumentItem',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',        models.CharField(max_length=200, verbose_name='اسم الورقة')),
                ('description', models.TextField(blank=True, verbose_name='التفاصيل والملاحظات')),
                ('is_required', models.BooleanField(default=True, verbose_name='مطلوب')),
                ('order',       models.PositiveIntegerField(default=0, verbose_name='الترتيب')),
                ('category',    models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='chatapp.officialdocumentcategory',
                    verbose_name='التصنيف',
                )),
            ],
            options={
                'verbose_name':        'ورقة رسمية',
                'verbose_name_plural': 'الأوراق الرسمية',
                'ordering':            ['order', 'name'],
            },
        ),
    ]
