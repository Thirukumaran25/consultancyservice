import time
from django.http import JsonResponse
from django.core.cache import cache

class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Rate limits: Adjust as needed (e.g., 5 per minute for login/apply, 20 per minute for chatbot)
        limits = {
            '/login/': {'rate': 5, 'window': 60},  # 5 requests per 60 seconds
            '/apply/': {'rate': 10, 'window': 3600},  # 10 per hour (adjust for dynamic paths)
            '/chatbot/': {'rate': 20, 'window': 60},
        }
        
        for path, config in limits.items():
            if path in request.path:  # Simple path match; use regex for dynamic paths
                ip = request.META.get('REMOTE_ADDR')
                key = f"ratelimit:{ip}:{path}"
                requests = cache.get(key, [])
                now = time.time()
                # Filter requests within the window
                requests = [r for r in requests if now - r < config['window']]
                if len(requests) >= config['rate']:
                    return JsonResponse({'error': 'Rate limit exceeded. Try again later.'}, status=429)
                requests.append(now)
                cache.set(key, requests, config['window'])
                break
        
        return self.get_response(request)