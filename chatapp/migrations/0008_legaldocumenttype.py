from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatapp', '0007_officialitem_name_textfield'),
    ]

    operations = [
        migrations.CreateModel(
            name='LegalDocumentType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.CharField(max_length=60, unique=True, verbose_name='المعرّف')),
                ('name', models.CharField(max_length=200, verbose_name='الاسم')),
                ('icon', models.CharField(default='📄', max_length=10, verbose_name='الأيقونة')),
                ('description', models.TextField(blank=True, verbose_name='الوصف')),
                ('is_active', models.BooleanField(default=True, verbose_name='مفعّل')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='الترتيب')),
            ],
            options={
                'verbose_name': 'نوع وثيقة قانونية',
                'verbose_name_plural': 'أنواع الوثائق القانونية',
                'ordering': ['order', 'name'],
            },
        ),
    ]
