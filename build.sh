#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# تحميل البيانات الأولية (محامين + وثائق) إذا لم تكن موجودة
python manage.py shell -c "
from chatapp.models import LawyerProfile
if not LawyerProfile.objects.exists():
    import subprocess
    subprocess.run(['python', 'manage.py', 'loaddata', 'initial_data.json'], check=True)
    print('✓ تم تحميل البيانات الأولية')
else:
    print('- البيانات موجودة مسبقاً، تم التخطي')
"

# إنشاء superuser تلقائياً إذا لم يكن موجوداً
python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
if not U.objects.filter(is_superuser=True).exists():
    U.objects.create_superuser('admin', 'admin@legal.sy', 'Admin1234!')
    print('✓ تم إنشاء حساب الإدارة: admin / Admin1234!')
else:
    print('- حساب الإدارة موجود مسبقاً')
"
