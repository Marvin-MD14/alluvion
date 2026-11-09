# flood/api.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import FloodEvent
from .services import pipeline


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_real_prediction_api(request):
    """
    Pinapatakbo ang buong prediction pipeline para sa isang event:
    lahat ng Sentinel-1 images (kada imagery type) na malapit sa petsa ng event.
    """
    event_id = request.data.get('event_id')
    if not event_id:
        return Response({'status': 'error', 'message': 'Event ID is required.'}, status=400)

    try:
        event = FloodEvent.objects.get(id=event_id)
    except (FloodEvent.DoesNotExist, ValueError):
        return Response({'status': 'error', 'message': 'Event not found.'}, status=404)

    try:
        predictions, messages = pipeline.run_all_for_event(event)
    except Exception as exc:  # noqa: BLE001
        return Response({'status': 'error', 'message': f'Prediction failed: {exc}'}, status=500)

    if not predictions:
        return Response({'status': 'error',
                         'message': ' '.join(messages) or 'Walang prediction na nagawa.'}, status=400)

    return Response({
        'status': 'success',
        'count': len(predictions),
        'messages': messages,
        'prediction_ids': [p.id for p in predictions],
    })
