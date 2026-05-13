"""
سكريبت إعداد المحامين التجريبيين.
ضعه في مجلد المشروع (نفس مستوى manage.py) وشغّله:
    python add_lawyers_setup.py
"""
import os, sys, django

# ─── إعداد Django ───────────────────────────────
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mcp_app.settings')
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)
django.setup()

from django.contrib.auth.models import User
from chatapp.models import LawyerProfile, UserProfile

# ─── بيانات المحامين ────────────────────────────
LAWYERS = [
    dict(username="a.khatib",  first="أحمد",  last="الخطيب",  spec="civil",
         office="مكتب الخطيب للمحاماة",        addr="دمشق - شارع بغداد - مبنى 12",
         lat=33.5138, lng=36.2765, fee=15000, exp=12,
         phone="011-2234567", email="khatib@law.sy",
         rating=4.8, reviews=42, lic="DAM-2012-0041"),

    dict(username="s.masri",   first="سارة",  last="المصري",   spec="family",
         office="مكتب المصري للأحوال الشخصية", addr="دمشق - المزة - شارع الجلاء 5",
         lat=33.5020, lng=36.2460, fee=12000, exp=8,
         phone="011-5554321", email="masri@law.sy",
         rating=4.5, reviews=28, lic="DAM-2016-0087"),

    dict(username="m.ali",     first="محمود", last="العلي",    spec="criminal",
         office="مكتب العلي للمحاماة الجنائية", addr="حلب - الجميلية - شارع الفردوس 3",
         lat=36.2021, lng=37.1343, fee=18000, exp=15,
         phone="021-2345678", email="ali@law.sy",
         rating=4.9, reviews=61, lic="ALP-2009-0012"),

    dict(username="n.deeb",    first="نور",   last="الديب",    spec="commercial",
         office="مكتب الديب التجاري",          addr="حمص - الوعر - شارع الحمراء 7",
         lat=34.7324, lng=36.7137, fee=14000, exp=10,
         phone="031-3456789", email="deeb@law.sy",
         rating=4.3, reviews=35, lic="HMS-2014-0033"),

    dict(username="k.suliman", first="كريم",  last="سليمان",   spec="real_estate",
         office="مكتب سليمان العقاري",         addr="اللاذقية - الزراعة - شارع 8 آذار",
         lat=35.5317, lng=35.7916, fee=13000, exp=9,
         phone="041-4567890", email="suliman@law.sy",
         rating=4.6, reviews=19, lic="LAT-2015-0055"),

    dict(username="r.hassoun", first="ريم",   last="حسون",     spec="labor",
         office="مكتب حسون لقانون العمل",      addr="طرطوس - شارع الكورنيش 14",
         lat=34.8958, lng=35.8869, fee=11000, exp=7,
         phone="043-5678901", email="hassoun@law.sy",
         rating=4.2, reviews=14, lic="TAR-2017-0021"),

    dict(username="o.rifai",   first="عمر",   last="الرفاعي",  spec="administrative",
         office="مكتب الرفاعي الإداري",        addr="دير الزور - شارع العروبة 2",
         lat=35.3359, lng=40.1400, fee=10000, exp=6,
         phone="051-6789012", email="rifai@law.sy",
         rating=4.4, reviews=22, lic="DEZ-2018-0009"),

    dict(username="h.jumai",   first="هلا",   last="جمعة",     spec="intellectual",
         office="مكتب جمعة للملكية الفكرية",  addr="درعا - المحطة - شارع الاستقلال",
         lat=32.6243, lng=36.1031, fee=12000, exp=8,
         phone="015-7890123", email="jumai@law.sy",
         rating=4.7, reviews=31, lic="DRA-2016-0044"),

    dict(username="w.najjar",  first="وسيم",  last="نجار",     spec="civil",
         office="مكتب نجار للقانون المدني",    addr="دمشق - باب توما - شارع النوفرة",
         lat=33.5117, lng=36.3174, fee=16000, exp=13,
         phone="011-1122334", email="najjar@law.sy",
         rating=4.6, reviews=38, lic="DAM-2011-0068"),

    dict(username="l.hassan",  first="لمى",   last="الحسن",    spec="family",
         office="مكتب الحسن للأسرة",           addr="حمص - الحميدية - شارع القوتلي 11",
         lat=34.7245, lng=36.7052, fee=13500, exp=9,
         phone="031-9988776", email="hassan@law.sy",
         rating=4.4, reviews=25, lic="HMS-2015-0077"),
]

# ─── إنشاء المحامين ─────────────────────────────
created = skipped = 0
for d in LAWYERS:
    existing_user = User.objects.filter(username=d['username']).first()
    if existing_user:
        if not hasattr(existing_user, 'profile'):
            UserProfile.objects.create(user=existing_user, user_type='lawyer')
            print(f"  ✅ أنشئت UserProfile للمستخدم الموجود: {d['first']} {d['last']}")
        skipped += 1
        print(f"  موجود: {d['first']} {d['last']}")
        continue

    user = User.objects.create_user(
        username   = d['username'],
        password   = 'Lawyer@2024',
        first_name = d['first'],
        last_name  = d['last'],
        email      = d['email'],
    )
    UserProfile.objects.get_or_create(user=user, defaults={'user_type': 'lawyer'})
    LawyerProfile.objects.create(
        user             = user,
        license_number   = d['lic'],
        specialization   = d['spec'],
        experience_years = d['exp'],
        office_name      = d['office'],
        office_address   = d['addr'],
        office_phone     = d['phone'],
        office_email     = d['email'],
        latitude         = d['lat'],
        longitude        = d['lng'],
        consultation_fee = d['fee'],
        rating           = d['rating'],
        total_reviews    = d['reviews'],
        is_verified      = True,
        is_available     = True,
        description      = f"محامٍ متخصص · خبرة {d['exp']} سنوات",
        languages        = 'العربية',
    )
    created += 1
    print(f"  ✅ {d['first']} {d['last']} | {d['addr']}")

print(f"\n{'='*40}")
print(f"تم إنشاء: {created} محامٍ")
print(f"موجود مسبقاً: {skipped}")
total = LawyerProfile.objects.filter(is_verified=True, latitude__isnull=False).count()
print(f"إجمالي المحامين على الخريطة: {total}")