"""
Django settings for mcp_app project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("DJANGO_SECRET_KEY environment variable is not set!")

DEBUG = os.getenv('DJANGO_DEBUG', 'False') == 'True'

#ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
ALLOWED_HOSTS = ['*']
# ==================== Auth URLs ====================
# "/" هو صفحة تسجيل الدخول
LOGIN_URL = '/'
LOGIN_REDIRECT_URL = '/index/'
LOGOUT_REDIRECT_URL = '/'

# ==================== Apps ====================
INSTALLED_APPS = [
    'chatapp',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

SESSION_ENGINE = 'django.contrib.sessions.backends.db'  # Database backend
SESSION_COOKIE_AGE = 3600 
SESSION_SAVE_EVERY_REQUEST = True

ROOT_URLCONF = 'mcp_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'chatapp' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mcp_app.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.sqlite3'),
        'NAME': os.getenv('DB_NAME', BASE_DIR / 'db.sqlite3'),
        'USER': os.getenv('DB_USER', ''),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Asia/Damascus'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==================== APIs ====================
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY', '')
PINECONE_ENV = os.getenv('PINECONE_ENV', 'gcp-starter')
PINECONE_INDEX_NAME = os.getenv('PINECONE_INDEX_NAME', 'legal-index')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
OPENAI_MAX_TOKENS = int(os.getenv('OPENAI_MAX_TOKENS', '1000'))

RAG_TOP_K_RESULTS = int(os.getenv('RAG_TOP_K_RESULTS', '3'))
RAG_MAX_CHUNK_SIZE = int(os.getenv('RAG_MAX_CHUNK_SIZE', '2000'))
RAG_BATCH_SIZE = int(os.getenv('RAG_BATCH_SIZE', '50'))

MAPTILER_API_KEY = os.getenv('MAPTILER_API_KEY', '')

USE_WHISPER_API = os.getenv('USE_WHISPER_API', 'True') == 'True'
MAX_AUDIO_SIZE = 10 * 1024 * 1024
ALLOWED_AUDIO_FORMATS = ['.mp3', '.wav', '.m4a', '.ogg', '.webm']

# ==================== Email ====================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'anasdib49@gmail.com' 
EMAIL_HOST_PASSWORD = 'gfsxpepayeliwlan'
DEFAULT_FROM_EMAIL =  'legal <anasdib49@gmail.com>'


''' 

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
''' 
# ==================== Upload Limits ====================
MAX_PDF_SIZE = 20 * 1024 * 1024
MAX_IMAGE_SIZE = 5 * 1024 * 1024

# ==================== Pagination ====================
LAWYERS_PER_PAGE = 12
CONSULTATIONS_PER_PAGE = 10
FEEDBACKS_PER_PAGE = 20
DEFAULT_SEARCH_RADIUS_KM = 50

# ==================== Logging ====================
import os
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose','stream': 'ext://sys.stdout'},
        'file': {'class': 'logging.FileHandler', 'filename': BASE_DIR / 'logs' / 'django.log', 'formatter': 'verbose','encoding': 'utf-8'},
    },
    'root': {'handlers': ['console', 'file'], 'level': 'INFO'},
    'loggers': {
        'django':  {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'chatapp': {'handlers': ['console', 'file'], 'level': 'DEBUG' if DEBUG else 'INFO', 'propagate': False},
    },
}

# ==================== Production Security ====================
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'syrian-legal-cache',
        'TIMEOUT': 1800,
    }
}