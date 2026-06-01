import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('chatapp', '0001_initial')]

    operations = [

        # ── حقول جديدة على Document ──
        migrations.AddField('document', 'articles_count',
            models.PositiveIntegerField(default=0, verbose_name='عدد المواد المفهرسة')),
        migrations.AddField('document', 'pinecone_chunks',
            models.PositiveIntegerField(default=0, verbose_name='مقاطع Pinecone')),
        migrations.AddField('document', 'is_indexed',
            models.BooleanField(default=False, verbose_name='مفهرس')),

        # ── جدول LegalArticle ──
        migrations.CreateModel(
            name='LegalArticle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('doc', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='articles', to='chatapp.document', db_index=True)),
                ('article_number',         models.PositiveIntegerField(db_index=True)),
                ('article_number_display', models.CharField(max_length=60)),
                ('section_path',           models.CharField(max_length=500, blank=True, db_index=True)),
                ('text',                   models.TextField()),
                ('order_in_doc',           models.PositiveIntegerField(default=0, db_index=True)),
            ],
            options={
                'verbose_name': 'مادة قانونية',
                'verbose_name_plural': 'المواد القانونية',
                'ordering': ['doc', 'order_in_doc'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='legalarticle',
            unique_together={('doc', 'article_number')},
        ),
        migrations.AddIndex('legalarticle',
            models.Index(fields=['doc', 'article_number'], name='idx_doc_artnum')),
        migrations.AddIndex('legalarticle',
            models.Index(fields=['section_path'], name='idx_section_path')),
    ]