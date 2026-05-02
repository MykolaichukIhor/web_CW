# your_app/middleware.py
from django.utils.deprecation import MiddlewareMixin

class DeviceDetectionMiddleware(MiddlewareMixin):
    """
    Middleware для визначення типу пристрою за User-Agent.
    """
    def process_request(self, request):
        # Отримуємо User-Agent з заголовків запиту
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        
        # Перевіряємо, чи є в ньому ключові слова мобільних пристроїв
        is_mobile = any(device in user_agent for device in [
            'mobile', 'android', 'iphone', 'ipad', 'ipod', 
            'blackberry', 'windows phone', 'opera mini', 'iemobile'
        ])

        # Додаємо прапорець до об'єкта request
        # Тепер у будь-якому view і навіть у шаблоні це буде доступно
        request.is_mobile = is_mobile