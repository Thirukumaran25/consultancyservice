from .models import Notification

def notification_count(request):
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).count()

        latest_notifications = Notification.objects.filter(
            user=request.user
        ).order_by('-created_at')[:5]
    else:
        unread_count = 0
        latest_notifications = []

    return {
        'notification_count': unread_count,
        'latest_notifications': latest_notifications,
    }
