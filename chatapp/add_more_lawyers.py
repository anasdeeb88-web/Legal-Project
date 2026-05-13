"""
سكريبت إضافة محامين جدد مع معلومات كاملة.
ضعه في مجلد المشروع (نفس مستوى manage.py) وشغّله:
    python add_more_lawyers.py
"""
import os, sys, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mcp_app.settings')
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)
django.setup()

from django.contrib.auth.models import User
from chatapp.models import LawyerProfile, UserProfile

LAWYERS = [
    dict(
        username="f.ibrahim", first="فارس", last="إبراهيم",
        email="f.ibrahim@law.sy", spec="criminal",
        office="مكتب إبراهيم للمحاماة الجنائية",
        addr="دمشق - ساحة المرجة - شارع النصر 8",
        lat=33.5102, lng=36.2923, fee=20000, exp=18,
        phone="011-3344556", lic="DAM-2006-0019",
        rating=4.9, reviews=74,
        desc="متخصص في القضايا الجنائية والدفاع الجزائي — خبرة 18 عاماً أمام محاكم دمشق",
        langs="العربية، الفرنسية"
    ),
    dict(
        username="m.qasim", first="منى", last="قاسم",
        email="m.qasim@law.sy", spec="family",
        office="مكتب قاسم للأحوال الشخصية",
        addr="دمشق - المالكي - شارع أبو رمانة 14",
        lat=33.5230, lng=36.2810, fee=13000, exp=11,
        phone="011-6677889", lic="DAM-2013-0102",
        rating=4.7, reviews=53,
        desc="متخصصة في قضايا الطلاق، الحضانة، النفقة، والميراث",
        langs="العربية"
    ),
    dict(
        username="z.sabbagh", first="زياد", last="الصباغ",
        email="z.sabbagh@law.sy", spec="commercial",
        office="مكتب الصباغ للقانون التجاري",
        addr="حلب - العزيزية - شارع بارون 22",
        lat=36.2100, lng=37.1580, fee=22000, exp=20,
        phone="021-5566778", lic="ALP-2004-0007",
        rating=5.0, reviews=89,
        desc="خبير في العقود التجارية، الشركات، والتحكيم الدولي",
        langs="العربية، الإنجليزية"
    ),
    dict(
        username="r.nassar", first="رنا", last="نصار",
        email="r.nassar@law.sy", spec="real_estate",
        office="مكتب نصار العقاري",
        addr="حمص - الحمراء - شارع القوتلي 33",
        lat=34.7400, lng=36.7200, fee=15000, exp=13,
        phone="031-2233445", lic="HMS-2011-0048",
        rating=4.6, reviews=40,
        desc="متخصصة في عقود البيع والشراء، التوثيق العقاري، ونزاعات الملكية",
        langs="العربية"
    ),
    dict(
        username="t.halabi", first="طارق", last="الحلبي",
        email="t.halabi@law.sy", spec="labor",
        office="مكتب الحلبي لقانون العمل والتأمينات",
        addr="اللاذقية - الرمل الشمالي - شارع 14 تشرين 7",
        lat=35.5450, lng=35.7980, fee=11000, exp=9,
        phone="041-9988112", lic="LAT-2015-0031",
        rating=4.5, reviews=26,
        desc="متخصص في قضايا العمال، عقود العمل، التعويضات، وإصابات العمل",
        langs="العربية"
    ),
    dict(
        username="s.barakat", first="سلمى", last="بركات",
        email="s.barakat@law.sy", spec="administrative",
        office="مكتب بركات للقانون الإداري",
        addr="طرطوس - شارع الوحدة 18",
        lat=34.8900, lng=35.8800, fee=12000, exp=8,
        phone="043-7766554", lic="TAR-2016-0014",
        rating=4.4, reviews=21,
        desc="متخصصة في الطعون الإدارية، قرارات الفصل، والتظلمات الحكومية",
        langs="العربية"
    ),
    dict(
        username="n.kurdi", first="نادر", last="الكردي",
        email="n.kurdi@law.sy", spec="intellectual",
        office="مكتب الكردي للملكية الفكرية والتكنولوجيا",
        addr="دمشق - كفرسوسة - شارع المتحلق الجنوبي 5",
        lat=33.4900, lng=36.2700, fee=18000, exp=10,
        phone="011-4455667", lic="DAM-2014-0076",
        rating=4.8, reviews=34,
        desc="متخصص في براءات الاختراع، حقوق النشر، والعلامات التجارية",
        langs="العربية، الإنجليزية"
    ),
    dict(
        username="h.mardini", first="هاني", last="المارديني",
        email="h.mardini@law.sy", spec="civil",
        office="مكتب المارديني للقانون المدني",
        addr="دمشق - باب مصلى - شارع الثورة 11",
        lat=33.5000, lng=36.3050, fee=14000, exp=15,
        phone="011-8899001", lic="DAM-2009-0055",
        rating=4.7, reviews=61,
        desc="متخصص في عقود المدنية، التعويضات، المسؤولية التقصيرية",
        langs="العربية"
    ),
    dict(
        username="l.yaziji", first="لارا", last="اليازجي",
        email="l.yaziji@law.sy", spec="family",
        office="مكتب اليازجي للأسرة والطفل",
        addr="حلب - السبيل - شارع الصفصاف 3",
        lat=36.1950, lng=37.1450, fee=11000, exp=7,
        phone="021-3344221", lic="ALP-2017-0091",
        rating=4.5, reviews=29,
        desc="متخصصة في قضايا الأسرة، حقوق الطفل، التبني، والوصاية",
        langs="العربية"
    ),
    dict(
        username="w.abboud", first="وليد", last="عبود",
        email="w.abboud@law.sy", spec="criminal",
        office="مكتب عبود للدفاع الجنائي",
        addr="دمشق - القصاع - شارع الجامع 6",
        lat=33.5180, lng=36.3100, fee=17000, exp=14,
        phone="011-2200330", lic="DAM-2010-0033",
        rating=4.6, reviews=48,
        desc="متخصص في قضايا الجنح والجنايات، والاستئنافات الجزائية",
        langs="العربية"
    ),
    dict(
        username="a.hamwi", first="أميرة", last="الحموي",
        email="a.hamwi@law.sy", spec="commercial",
        office="مكتب الحموي للأعمال والاستثمار",
        addr="دمشق - المزرعة - شارع المتنبي 20",
        lat=33.5160, lng=36.2880, fee=25000, exp=16,
        phone="011-5544332", lic="DAM-2008-0029",
        rating=4.9, reviews=67,
        desc="خبيرة في قانون الاستثمار، الشركات متعددة الجنسيات، وعقود BOT",
        langs="العربية، الإنجليزية، الفرنسية"
    ),
    dict(
        username="k.khouri", first="كارم", last="الخوري",
        email="k.khouri@law.sy", spec="real_estate",
        office="مكتب الخوري للمنازعات العقارية",
        addr="اللاذقية - الأمين - شارع بغداد 9",
        lat=35.5280, lng=35.7850, fee=13500, exp=12,
        phone="041-6655443", lic="LAT-2012-0022",
        rating=4.5, reviews=38,
        desc="متخصص في قضايا التعدي على العقارات، الحدود، وتقسيم الإرث",
        langs="العربية"
    ),
]

created = skipped = 0

for d in LAWYERS:
    if User.objects.filter(username=d['username']).exists():
        skipped += 1
        print(f"  موجود: {d['first']} {d['last']}")
        continue

    user = User.objects.create_user(
        username=d['username'],
        password='Lawyer@2024',
        first_name=d['first'],
        last_name=d['last'],
        email=d['email'],
    )

    # إنشاء UserProfile
    UserProfile.objects.get_or_create(user=user, defaults={'user_type': 'lawyer'})

    LawyerProfile.objects.create(
        user=user,
        license_number=d['lic'],
        specialization=d['spec'],
        experience_years=d['exp'],
        office_name=d['office'],
        office_address=d['addr'],
        office_phone=d['phone'],
        office_email=d['email'],
        latitude=d['lat'],
        longitude=d['lng'],
        consultation_fee=d['fee'],
        rating=d['rating'],
        total_reviews=d['reviews'],
        is_verified=True,
        is_available=True,
        description=d['desc'],
        languages=d['langs'],
    )
    created += 1
    print(f"  ✅ {d['first']} {d['last']} | {d['spec']} | {d['addr']}")

print(f"\n{'='*50}")
print(f"تم إنشاء : {created} محامٍ جديد")
print(f"موجود مسبقاً: {skipped}")
total = LawyerProfile.objects.filter(is_verified=True, latitude__isnull=False).count()
print(f"إجمالي المحامين على الخريطة الآن: {total}")
