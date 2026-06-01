from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatapp', '0006_generateddocument'),
    ]

    operations = [
        migrations.AlterField(
            model_name='officialdocumentitem',
            name='name',
            field=models.TextField(verbose_name='نص البند'),
        ),
    ]
