
from django.utils.deprecation import MiddlewareMixin

class DeviceDetectionMiddleware(MiddlewareMixin):
    """
    Middleware для визначення типу пристрою за User-Agent.
    """
    def process_request(self, request):
        
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        
        is_mobile = any(device in user_agent for device in [
            'mobile', 'android', 'iphone', 'ipad', 'ipod', 
            'blackberry', 'windows phone', 'opera mini', 'iemobile'
        ])

        
        
        request.is_mobile = is_mobile