from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatapp', '0004_official_documents'),
    ]

    operations = [
        migrations.AddField(
            model_name='officialdocumentcategory',
            name='color',
            field=models.CharField(
                default='linear-gradient(135deg,#0b1628,#b8965a)',
                max_length=200,
                verbose_name='اللون / التدرج',
            ),
        ),
    ]
