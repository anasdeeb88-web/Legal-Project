"""
Management Command: رفع وفهرسة ملفات PDF القانونية

الاستخدام:
    # رفع مجلد كامل
    python manage.py index_laws /path/to/pdfs/

    # رفع ملف واحد
    python manage.py index_laws /path/to/laws/civil_code.pdf --title "القانون المدني"

    # فحص بدون رفع فعلي (dry-run)
    python manage.py index_laws /path/to/pdfs/ --dry-run

    # إعادة فهرسة وثيقة موجودة بالـ ID
    python manage.py index_laws --reindex 5

    # اختبار التعرف على المواد فقط (بدون رفع)
    python manage.py index_laws /path/to/law.pdf --test-parse
"""

import os
import sys
import time

from django.core.management.base import BaseCommand, CommandError
from django.core.files import File
from django.db import transaction


class Command(BaseCommand):
    help = 'رفع وفهرسة ملفات PDF القانونية في PostgreSQL و Pinecone'

    def add_arguments(self, parser):
        parser.add_argument(
            'path', nargs='?', type=str,
            help='مسار ملف PDF أو مجلد يحتوي ملفات PDF'
        )
        parser.add_argument(
            '--title', type=str, default='',
            help='عنوان الوثيقة (لملف واحد فقط)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='فحص فقط بدون حفظ في قاعدة البيانات'
        )
        parser.add_argument(
            '--test-parse', action='store_true',
            help='اختبار التعرف على المواد وعرض النتائج'
        )
        parser.add_argument(
            '--reindex', type=int, metavar='DOC_ID',
            help='إعادة فهرسة وثيقة موجودة بالـ ID'
        )
        parser.add_argument(
            '--skip-pinecone', action='store_true',
            help='تخطي Pinecone وخزّن في PostgreSQL فقط'
        )

    def handle(self, *args, **options):
        # ── إعادة فهرسة وثيقة موجودة ──
        if options.get('reindex'):
            self._reindex_existing(options['reindex'], options)
            return

        path = options.get('path')
        if not path:
            raise CommandError('يجب تحديد مسار أو استخدام --reindex')

        if not os.path.exists(path):
            raise CommandError(f'المسار غير موجود: {path}')

        # ملف واحد أو مجلد
        if os.path.isfile(path):
            files = [path]
        else:
            files = sorted([
                os.path.join(path, f)
                for f in os.listdir(path)
                if f.lower().endswith('.pdf')
            ])

        if not files:
            raise CommandError(f'لا توجد ملفات PDF في: {path}')

        self.stdout.write(f'\n{"="*60}')
        self.stdout.write(f'📂 وجد {len(files)} ملف PDF')
        self.stdout.write(f'{"="*60}\n')

        results = {'success': 0, 'failed': 0, 'skipped': 0}

        for i, filepath in enumerate(files, 1):
            filename = os.path.basename(filepath)
            title = options['title'] if (options['title'] and len(files) == 1) else \
                    os.path.splitext(filename)[0]

            self.stdout.write(f'\n[{i}/{len(files)}] 📄 {title}')
            self.stdout.write(f'    المسار: {filepath}')

            try:
                if options['test_parse']:
                    self._test_parse(filepath, title)
                    continue

                if options['dry_run']:
                    self._dry_run(filepath, title)
                    results['skipped'] += 1
                    continue

                ok = self._process_file(filepath, title, options)
                if ok:
                    results['success'] += 1
                else:
                    results['failed'] += 1

            except KeyboardInterrupt:
                self.stdout.write('\n⚠️  توقف يدوي')
                break
            except Exception as e:
                self.stderr.write(f'    ❌ خطأ: {e}')
                results['failed'] += 1

        self.stdout.write(f'\n{"="*60}')
        self.stdout.write(
            f'✅ نجح: {results["success"]} | '
            f'❌ فشل: {results["failed"]} | '
            f'⏭ تجاهل: {results["skipped"]}'
        )
        self.stdout.write(f'{"="*60}\n')

    # ──────────────────────────────────────────────────────────
    def _process_file(self, filepath: str, title: str, options: dict) -> bool:
        """معالجة ملف PDF واحد: استخراج + فهرسة"""
        from chatapp.models import Document
        from chatapp.rag_utils import (
            store_document_in_pinecone,
            _store_legal_articles,
            clean_text,
            ARTICLE_RE,
        )
        import PyPDF2

        # 1. استخراج النص
        self.stdout.write('    ⏳ استخراج النص...')
        text = self._extract_text(filepath)

        if not text.strip():
            self.stderr.write('    ❌ النص فارغ — تأكد أن الـ PDF يحتوي نصاً وليس صوراً')
            return False

        self.stdout.write(f'    ✓ النص: {len(text):,} حرف')

        # 2. فحص وجود مواد
        cleaned = clean_text(text)
        found = ARTICLE_RE.findall(cleaned)
        self.stdout.write(f'    ✓ مواد مكتشفة بـ ARTICLE_RE: {len(found)}')

        if len(found) == 0:
            self.stderr.write('    ⚠️  لم يُعثر على أي مادة — تحقق من تنسيق الـ PDF')
            self.stdout.write(f'    أول 300 حرف بعد التنظيف:\n    {cleaned[:300]}')

        # 3. إنشاء Document في DB
        self.stdout.write('    ⏳ حفظ في قاعدة البيانات...')
        with open(filepath, 'rb') as f:
            doc = Document.objects.create(
                title=title,
                file=File(f, name=os.path.basename(filepath)),
            )
        doc.extracted_text = text
        doc.save()
        self.stdout.write(f'    ✓ Document #{doc.id} أُنشئ')

        # 4. فهرسة
        if options.get('skip_pinecone'):
            self.stdout.write('    ⏳ فهرسة PostgreSQL فقط...')
            art_count = _store_legal_articles(doc.id, text, doc_title=title)
            self.stdout.write(f'    ✓ PostgreSQL: {art_count} مادة')
            chunks = 0
        else:
            self.stdout.write('    ⏳ فهرسة Pinecone + PostgreSQL...')
            t0 = time.time()
            chunks = store_document_in_pinecone(doc.id, text, doc_title=title)
            elapsed = round(time.time() - t0, 1)

            from chatapp.models import LegalArticle
            art_count = LegalArticle.objects.filter(doc_id=doc.id).count()
            self.stdout.write(
                f'    ✓ Pinecone: {chunks} chunk | '
                f'PostgreSQL: {art_count} مادة | '
                f'وقت: {elapsed}s'
            )

        if chunks == 0 and art_count == 0:
            self.stderr.write('    ❌ فشلت الفهرسة — راجع الـ logs')
            return False

        self.stdout.write(self.style.SUCCESS(f'    ✅ "{title}" فُهرست بنجاح'))
        return True

    # ──────────────────────────────────────────────────────────
    def _test_parse(self, filepath: str, title: str):
        """اختبار التعرف على المواد بدون حفظ"""
        from chatapp.rag_utils import clean_text, _parse_document, ARTICLE_RE

        self.stdout.write('    🔬 وضع الاختبار...')
        text = self._extract_text(filepath)
        cleaned = clean_text(text)

        found_re = ARTICLE_RE.findall(cleaned)
        self.stdout.write(f'    ARTICLE_RE: {len(found_re)} مادة')

        tree = _parse_document(cleaned)
        total = sum(len(s["articles"]) for s in tree)

        self.stdout.write(f'    _parse_document: {total} مادة في {len(tree)} قسم')

        # عرض أول 10 مواد
        self.stdout.write('\n    أول 10 مواد:')
        count = 0
        for section in tree:
            for art in section["articles"]:
                if count >= 10:
                    break
                self.stdout.write(
                    f'      [{art["num_int"]}] {art["num"]} | '
                    f'نص: {art["text"][:60].strip()}...'
                )
                count += 1

        # عرض أي مواد اكتشفها ARTICLE_RE لكن _parse_document فاتها
        if len(found_re) > total:
            self.stdout.write(
                f'\n    ⚠️  ARTICLE_RE وجد {len(found_re)} لكن parse حفظ {total} — '
                f'فرق {len(found_re) - total} مادة'
            )
            # عرض أمثلة على المواد المفقودة
            parsed_labels = {a["num"] for s in tree for a in s["articles"]}
            self.stdout.write('    أمثلة مواد وجدها RE لكن فاتت parse:')
            shown = 0
            for label in found_re:
                label_clean = label.strip()
                if label_clean not in parsed_labels and shown < 5:
                    # ابحث عن السياق
                    idx = cleaned.find(label_clean)
                    ctx = cleaned[max(0, idx-30):idx+80] if idx >= 0 else ''
                    self.stdout.write(f'      "{label_clean}" ... سياق: {repr(ctx)}')
                    shown += 1

    # ──────────────────────────────────────────────────────────
    def _dry_run(self, filepath: str, title: str):
        """فحص بدون حفظ"""
        from chatapp.rag_utils import clean_text, ARTICLE_RE

        text = self._extract_text(filepath)
        cleaned = clean_text(text)
        found = ARTICLE_RE.findall(cleaned)

        self.stdout.write(
            f'    [DRY-RUN] النص: {len(text):,} حرف | '
            f'مواد مكتشفة: {len(found)}'
        )

    # ──────────────────────────────────────────────────────────
    def _reindex_existing(self, doc_id: int, options: dict):
        """إعادة فهرسة وثيقة موجودة"""
        from chatapp.models import Document, LegalArticle
        from chatapp.rag_utils import (
            store_document_in_pinecone,
            _store_legal_articles,
            clean_text, ARTICLE_RE,
        )

        try:
            doc = Document.objects.get(pk=doc_id)
        except Document.DoesNotExist:
            raise CommandError(f'لا توجد وثيقة بالـ ID: {doc_id}')

        self.stdout.write(f'\n🔄 إعادة فهرسة: "{doc.title}" (#{doc_id})')

        # استخراج النص
        if not doc.extracted_text:
            self.stdout.write('⏳ استخراج النص من الملف...')
            text = self._extract_text(doc.file.path)
            doc.extracted_text = text
            doc.save()
        else:
            text = doc.extracted_text
            self.stdout.write(f'✓ نص محفوظ: {len(text):,} حرف')

        cleaned = clean_text(text)
        found = ARTICLE_RE.findall(cleaned)
        self.stdout.write(f'✓ ARTICLE_RE: {len(found)} مادة')

        # حذف Pinecone القديم
        if not options.get('skip_pinecone'):
            try:
                from chatapp.rag_utils import index as pc_index
                pc_index.delete(filter={"doc_id": str(doc_id)})
                self.stdout.write('✓ حُذفت vectors Pinecone القديمة')
            except Exception as e:
                self.stdout.write(f'⚠️  فشل حذف Pinecone: {e}')

        # إعادة الفهرسة
        if options.get('skip_pinecone'):
            art_count = _store_legal_articles(doc_id, text, doc_title=doc.title)
            self.stdout.write(self.style.SUCCESS(f'✅ PostgreSQL: {art_count} مادة'))
        else:
            chunks = store_document_in_pinecone(doc_id, text, doc_title=doc.title)
            art_count = LegalArticle.objects.filter(doc_id=doc_id).count()
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Pinecone: {chunks} chunk | PostgreSQL: {art_count} مادة'
                )
            )

    # ──────────────────────────────────────────────────────────
    @staticmethod
    def _extract_text(filepath: str) -> str:
        import PyPDF2

        try:
            pages = []
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    t = page.extract_text() or ''
                    if t.strip():
                        pages.append(t)
            return '\n\n'.join(pages)
        except Exception as e:
            raise CommandError(f'فشل استخراج النص: {e}')