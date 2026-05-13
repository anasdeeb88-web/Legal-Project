"""
معالجة الملفات الصوتية والتحويل إلى نص
"""

import speech_recognition as sr
from openai import OpenAI
from django.conf import settings
import os
import logging

logger = logging.getLogger(__name__)


def transcribe_audio_whisper(audio_file_path):
    """
    تحويل الصوت إلى نص باستخدام OpenAI Whisper
    """
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        
        with open(audio_file_path, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ar"  # اللغة العربية
            )
        
        logger.info(f"تم تحويل الصوت بنجاح: {audio_file_path}")
        return transcript.text
        
    except Exception as e:
        logger.error(f"فشل تحويل الصوت: {e}")
        return ""


def transcribe_audio_google(audio_file_path):
    """
    تحويل الصوت إلى نص باستخدام Google Speech Recognition (مجاني)
    """
    try:
        recognizer = sr.Recognizer()
        
        with sr.AudioFile(audio_file_path) as source:
            audio = recognizer.record(source)
        
        # استخدام Google Speech Recognition
        text = recognizer.recognize_google(audio, language='ar-SA')
        
        logger.info(f"تم تحويل الصوت بنجاح (Google): {audio_file_path}")
        return text
        
    except sr.UnknownValueError:
        logger.warning("لم يتمكن من فهم الصوت")
        return ""
    except sr.RequestError as e:
        logger.error(f"خطأ في خدمة التعرف على الصوت: {e}")
        return ""
    except Exception as e:
        logger.error(f"خطأ غير متوقع: {e}")
        return ""


def process_audio_file(audio_file, use_whisper=True):
    """
    معالجة ملف صوتي وإرجاع النص
    
    Args:
        audio_file: Django UploadedFile object
        use_whisper: استخدام Whisper API (أفضل للعربية لكن مدفوع) أو Google (مجاني)
    
    Returns:
        str: النص المستخرج من الصوت
    """
    # حفظ الملف مؤقتاً
    temp_path = f"/tmp/{audio_file.name}"
    
    try:
        with open(temp_path, 'wb+') as destination:
            for chunk in audio_file.chunks():
                destination.write(chunk)
        
        # اختيار الطريقة
        if use_whisper and hasattr(settings, 'OPENAI_API_KEY'):
            text = transcribe_audio_whisper(temp_path)
        else:
            text = transcribe_audio_google(temp_path)
        
        return text
        
    finally:
        # حذف الملف المؤقت
        if os.path.exists(temp_path):
            os.remove(temp_path)