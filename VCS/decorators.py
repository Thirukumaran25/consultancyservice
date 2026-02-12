import time
from functools import wraps
from django.http import JsonResponse
from django.core.cache import cache

def rate_limit(rate='5/m'):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            ip = request.META.get('REMOTE_ADDR')
            key = f"ratelimit:{ip}:{view_func.__name__}"
            requests = cache.get(key, [])
            now = time.time()
            window = 60 if 'm' in rate else 3600  # Minutes or hours
            limit = int(rate.split('/')[0])
            requests = [r for r in requests if now - r < window]
            if len(requests) >= limit:
                return JsonResponse({'error': 'Rate limit exceeded.'}, status=429)
            requests.append(now)
            cache.set(key, requests, window)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator