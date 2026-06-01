from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatapp', '0008_legaldocumenttype'),
    ]

    operations = [
        migrations.AddField(
            model_name='lawyerprofile',
            name='mobile_phone',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='رقم الموبايل'),
        ),
    ]
