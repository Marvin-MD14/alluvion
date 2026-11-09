from .models import FloodPrediction

def notifications(request):
    if not request.user.is_authenticated:
        return {}
    latest = list(FloodPrediction.objects.select_related('flood_event').order_by('-created_at')[:5])
    return {
        'nav_notifications': latest,
        'nav_notif_latest_id': latest[0].id if latest else 0,
    }