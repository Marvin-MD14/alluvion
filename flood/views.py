# flood/views.py
import csv
import io
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count  # ✅ Idinagdag ang Count para sa Bar Chart
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import DrainageOutlet, FloodEvent, FloodPrediction, MapLegend
from .services import pipeline
from .services.ai_model import imagery_label
from .services.evaluation import latest_per_event_and_type

# Re-export para gumana sa urls.py
from .views_manage import events_view  # noqa: F401
from .views_reports import evaluation_view  # noqa: F401


# ------------------------------------------------------------------ #
# Dashboard (Line, Bar, at Pie Charts)
# ------------------------------------------------------------------ #
@login_required(login_url='/accounts/login/')
def dashboard_view(request):
    predictions = FloodPrediction.objects.select_related('flood_event').order_by('-created_at')
    events = FloodEvent.objects.order_by('-date_occurred')

    avg_iou = predictions.aggregate(Avg('iou_score'))['iou_score__avg'] or 0.0
    
    # --- 1. LINE CHART DATA (Last 5 Predictions) ---
    chart_data = list(predictions[:5])[::-1]
    chart_labels = [f'{p.flood_event.event_name}' for p in chart_data]
    chart_values = [p.predicted_magnitude_pixels for p in chart_data]

    # --- 2. BAR CHART DATA (Predictions per Imagery Type) ---
    # Kinukuha kung ilang beses ginamit ang bawat imagery type
    imagery_counts = FloodPrediction.objects.values('imagery_type').annotate(count=Count('id')).order_by('-count')
    bar_labels = [item['imagery_type'].upper().replace('_', ' ') for item in imagery_counts]
    bar_values = [item['count'] for item in imagery_counts]

    # --- 3. PIE CHART DATA (IoU Score Distribution) ---
    # High (>0.75), Medium (0.5-0.75), Low (<0.5)
    high_iou = predictions.filter(iou_score__gte=0.75).count()
    mid_iou = predictions.filter(iou_score__gte=0.5, iou_score__lt=0.75).count()
    low_iou = predictions.filter(iou_score__lt=0.5).count()
    pie_data = [high_iou, mid_iou, low_iou]

    context = {
        'predictions': predictions[:10],
        'events': events,
        'event_count': events.count(),
        'prediction_count': predictions.count(),
        'avg_iou': round(avg_iou, 2),
        
        # I-convert sa JSON para magamit sa JavaScript
        'chart_labels': json.dumps(chart_labels),
        'chart_values': json.dumps(chart_values),
        'bar_labels': json.dumps(bar_labels),
        'bar_values': json.dumps(bar_values),
        'pie_data': json.dumps(pie_data),
    }
    return render(request, 'flood/dashboard.html', context)


# ------------------------------------------------------------------ #
# Flood Map (dynamic legend + layers)
# ------------------------------------------------------------------ #
@login_required(login_url='/accounts/login/')
def map_view(request):
    preds = list(FloodPrediction.objects.select_related('flood_event').order_by('-created_at'))
    choices = latest_per_event_and_type(preds)
    choices.sort(key=lambda p: p.created_at, reverse=True)

    selected = None
    pid = request.GET.get('p')
    if pid and pid.isdigit():
        selected = next((p for p in preds if p.id == int(pid)), None)
    if selected is None and choices:
        selected = choices[0]

    event = selected.flood_event if selected else None
    legends = list(MapLegend.objects.filter(is_active=True).values(
        'id', 'name', 'category', 'color', 'description', 'order', 'geojson'
    ))

    context = {
        'choices': [
            {'id': p.id, 'label': f'{p.flood_event.event_name} - {imagery_label(p.imagery_type)}'}
            for p in choices
        ],
        'selected': selected,
        'event': event,
        'imagery_label': imagery_label(selected.imagery_type) if selected else '',
        'extent': selected.flood_extent_geojson if selected else None,
        'hazard': selected.hazard_geojson if selected else None,
        'reference': event.actual_extent_geojson if event else None,
        'outlets': list(DrainageOutlet.objects.values('name', 'latitude', 'longitude', 'elevation')),
        'legends': legends,
    }
    return render(request, 'flood/map.html', context)


# ------------------------------------------------------------------ #
# Notifications (paginated)
# ------------------------------------------------------------------ #
@login_required(login_url='/accounts/login/')
def notifications_view(request):
    items_list = FloodPrediction.objects.select_related('flood_event').order_by('-created_at')
    page_obj = Paginator(items_list, 10).get_page(request.GET.get('page'))

    return render(request, 'flood/notifications.html', {'items': page_obj})


# ------------------------------------------------------------------ #
# Run prediction API
# ------------------------------------------------------------------ #
@login_required
@require_POST
def run_prediction_api(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid request body.'}, status=400)

    event_id = payload.get('event_id')
    if not event_id:
        return JsonResponse({'status': 'error', 'message': 'Event ID is required.'}, status=400)

    event = get_object_or_404(FloodEvent, pk=event_id)

    try:
        predictions, messages_list = pipeline.run_all_for_event(event)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'status': 'error', 'message': f'Prediction failed: {exc}'}, status=500)

    if not predictions:
        return JsonResponse({
            'status': 'error',
            'message': ' '.join(messages_list) or 'No prediction was generated.',
        }, status=400)

    return JsonResponse({
        'status': 'success',
        'count': len(predictions),
        'messages': messages_list,
        'prediction_ids': [p.id for p in predictions],
    })


# ------------------------------------------------------------------ #
# Drainage Outlets (click-map coordinates + CSV import + pagination)
# ------------------------------------------------------------------ #
def _to_float(value, name):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'invalid {name}')


def _validate_outlet(name, lat, lng, elev):
    name = (name or '').strip()
    if not name:
        raise ValueError('name is required')
    lat, lng = _to_float(lat, 'latitude'), _to_float(lng, 'longitude')
    elev = _to_float(elev if str(elev or '').strip() != '' else 0, 'elevation')
    if not -90 <= lat <= 90:
        raise ValueError('latitude must be between -90 and 90')
    if not -180 <= lng <= 180:
        raise ValueError('longitude must be between -180 and 180')
    return name, lat, lng, elev


@login_required(login_url='/accounts/login/')
def outlets_view(request):
    if request.method == 'POST':
        # ---- CSV upload ----
        if 'csv_file' in request.FILES:
            csv_file = request.FILES['csv_file']
            if not csv_file.name.lower().endswith('.csv'):
                messages.error(request, 'This is not a CSV file.')
                return redirect('outlets')
            try:
                text = csv_file.read().decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(text))
                headers = [(h or '').strip().lower() for h in (reader.fieldnames or [])]
                missing = [c for c in ('name', 'latitude', 'longitude') if c not in headers]
                if missing:
                    raise ValueError('Missing columns: ' + ', '.join(missing))
                created = updated = 0
                errors = []
                for i, raw in enumerate(reader, start=2):
                    row = {(k or '').strip().lower(): v for k, v in raw.items()}
                    try:
                        name, lat, lng, elev = _validate_outlet(
                            row.get('name'), row.get('latitude'), row.get('longitude'), row.get('elevation'))
                        _, was_created = DrainageOutlet.objects.update_or_create(
                            name=name, defaults={'latitude': lat, 'longitude': lng, 'elevation': elev})
                        created += was_created
                        updated += (not was_created)
                    except ValueError as exc:
                        errors.append(f'Row {i}: {exc}')
                messages.success(request, f'CSV imported: {created} new, {updated} updated.')
                if errors:
                    messages.warning(request, f'{len(errors)} row(s) skipped. ' + ' | '.join(errors[:5]))
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f'Could not import the CSV: {exc}')
            return redirect('outlets')

        # ---- Single outlet ----
        if 'name' in request.POST:
            if not (request.POST.get('latitude') and request.POST.get('longitude')):
                messages.error(request, 'Please click a location on the map first.')
                return redirect('outlets')
            try:
                name, lat, lng, elev = _validate_outlet(
                    request.POST.get('name'), request.POST.get('latitude'),
                    request.POST.get('longitude'), request.POST.get('elevation'))
                DrainageOutlet.objects.create(name=name, latitude=lat, longitude=lng, elevation=elev)
                messages.success(request, 'Outlet added successfully.')
            except ValueError as exc:
                messages.error(request, f'Could not add outlet: {exc}.')
            return redirect('outlets')

    outlets_list = DrainageOutlet.objects.all().order_by('-id')
    page_obj = Paginator(outlets_list, 10).get_page(request.GET.get('page'))

    return render(request, 'flood/outlets.html', {
        'outlets': page_obj,
        'map_outlets': list(DrainageOutlet.objects.values('name', 'latitude', 'longitude', 'elevation')),
    })