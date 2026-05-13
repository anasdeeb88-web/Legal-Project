"""
Management command لإضافة محامين تجريبيين سوريين.
ضعه في: chatapp/management/commands/add_demo_lawyers.py
ثم نفّذ: python manage.py add_demo_lawyers
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from chatapp.models import LawyerProfile, UserProfile

LAWYERS = [
    dict(username='lawyer_damascus1',  first='أحمد',  last='الخطيب',  spec='civil',          office='مكتب الخطيب للمحاماة',          addr='دمشق - شارع بغداد - مبنى 12',       lat=33.5138, lng=36.2765, fee=15000, exp=12, phone='011-1234567', rating=4.8, reviews=42),
    dict(username='lawyer_damascus2',  first='سارة',  last='المصري',   spec='family',         office='مكتب المصري للأحوال الشخصية',   addr='دمشق - المزة - شارع الجلاء',        lat=33.5020, lng=36.2460, fee=12000, exp= 8, phone='011-7654321', rating=4.5, reviews=28),
    dict(username='lawyer_aleppo1',    first='محمود', last='العلي',    spec='criminal',       office='مكتب العلي للمحاماة الجنائية',  addr='حلب - الجميلية - شارع الفردوس',     lat=36.2021, lng=37.1343, fee=18000, exp=15, phone='021-2345678', rating=4.9, reviews=61),
    dict(username='lawyer_homs1',      first='نور',   last='الديب',    spec='commercial',     office='مكتب الديب التجاري',            addr='حمص - الوعر - شارع الحمراء',        lat=34.7324, lng=36.7137, fee=14000, exp=10, phone='031-3456789', rating=4.3, reviews=35),
    dict(username='lawyer_latakia1',   first='كريم',  last='سليمان',   spec='real_estate',    office='مكتب سليمان العقاري',           addr='اللاذقية - الزراعة - شارع 8 آذار',  lat=35.5317, lng=35.7916, fee=13000, exp= 9, phone='041-4567890', rating=4.6, reviews=19),
    dict(username='lawyer_tartus1',    first='ريم',   last='حسون',     spec='labor',          office='مكتب حسون لقانون العمل',        addr='طرطوس - شارع الكورنيش',             lat=34.8958, lng=35.8869, fee=11000, exp= 7, phone='043-5678901', rating=4.2, reviews=14),
    dict(username='lawyer_deirez1',    first='عمر',   last='الرفاعي',  spec='administrative', office='مكتب الرفاعي الإداري',          addr='دير الزور - شارع العروبة',          lat=35.3359, lng=40.1400, fee=10000, exp= 6, phone='051-6789012', rating=4.4, reviews=22),
    dict(username='lawyer_daraa1',     first='هلا',   last='جمعة',     spec='intellectual',   office='مكتب جمعة للملكية الفكرية',    addr='درعا - المحطة - شارع الاستقلال',   lat=32.6243, lng=36.1031, fee=12000, exp= 8, phone='015-7890123', rating=4.7, reviews=31),
]


class Command(BaseCommand):
    help = 'إضافة محامين تجريبيين سوريين مع إحداثيات حقيقية'

    def handle(self, *args, **options):
        created = 0
        for d in LAWYERS:
            existing_user = User.objects.filter(username=d['username']).first()
            if existing_user:
                if not hasattr(existing_user, 'profile'):
                    UserProfile.objects.create(user=existing_user, user_type='lawyer')
                    self.stdout.write(self.style.SUCCESS(f"  ✅ أنشئت UserProfile للمستخدم الموجود: {d['username']}"))
                else:
                    self.stdout.write(f"  موجود: {d['username']}")
                continue

            user = User.objects.create_user(
                username=d['username'],
                password='lawyer123',
                first_name=d['first'],
                last_name=d['last'],
                email=f"{d['username']}@law.sy",
            )
            UserProfile.objects.get_or_create(user=user, defaults={'user_type': 'lawyer'})

            LawyerProfile.objects.create(
                user=user,
                specialization=d['spec'],
                experience_years=d['exp'],
                office_name=d['office'],
                office_address=d['addr'],
                office_phone=d['phone'],
                office_email=f"{d['username']}@law.sy",
                latitude=d['lat'],
                longitude=d['lng'],
                consultation_fee=d['fee'],
                rating=d['rating'],
                total_reviews=d['reviews'],
                is_verified=True,
                is_available=True,
                license_number=f"SYR-{2010 + d['exp']}-{abs(hash(d['username'])) % 9999:04d}",
                description=f"محامٍ متخصص في {d['spec']} مع خبرة {d['exp']} سنوات",
                languages='العربية',
            )
            created += 1
            self.stdout.write(self.style.SUCCESS(f"  ✓ {d['first']} {d['last']} | {d['addr'][:40]}"))

        self.stdout.write(self.style.SUCCESS(f'\nتم إنشاء {created} محامٍ بنجاح'))
