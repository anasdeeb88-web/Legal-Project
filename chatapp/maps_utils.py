"""
وظائف الخرائط والجيولوكيشن — بدون Google Maps API
يستخدم Nominatim (OpenStreetMap) مجاناً
"""

from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import logging, time

logger = logging.getLogger(__name__)
_geolocator = Nominatim(user_agent="syrian-legal-advisor-v2", timeout=10)


def get_coordinates(address: str):
    if not address or not address.strip():
        return None, None
    try:
        time.sleep(1)  # Nominatim rate limit
        location = _geolocator.geocode(address, language='ar')
        if location:
            return location.latitude, location.longitude
        location = _geolocator.geocode(f"{address}, سوريا", language='ar')
        if location:
            return location.latitude, location.longitude
        return None, None
    except Exception as e:
        logger.error(f"فشل الإحداثيات: {e}")
        return None, None


def get_address_from_coordinates(lat: float, lng: float) -> str:
    try:
        time.sleep(1)
        loc = _geolocator.reverse(f"{lat}, {lng}", language='ar')
        return loc.address if loc else ""
    except Exception as e:
        logger.error(f"فشل العنوان: {e}")
        return ""


def calculate_distance(lat1, lng1, lat2, lng2):
    try:
        return round(geodesic((lat1, lng1), (lat2, lng2)).kilometers, 2)
    except Exception as e:
        logger.error(f"فشل المسافة: {e}")
        return None


def find_nearby_lawyers(user_lat: float, user_lng: float, max_distance_km: float = 50):
    from .models import LawyerProfile
    lawyers = LawyerProfile.objects.filter(
        latitude__isnull=False, longitude__isnull=False,
        is_verified=True, is_available=True,
    ).select_related('user')
    nearby = []
    for l in lawyers:
        dist = calculate_distance(user_lat, user_lng, float(l.latitude), float(l.longitude))
        if dist is not None and dist <= max_distance_km:
            nearby.append({'lawyer': l, 'distance': dist})
    nearby.sort(key=lambda x: x['distance'])
    return nearby