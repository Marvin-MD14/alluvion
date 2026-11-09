# flood/views_manage.py — English, dynamic, AJAX-ready
import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import FloodEventForm, OutletForm
from .models import DrainageOutlet, FloodEvent, FloodPrediction


# --------------------------- Flood Events --------------------------- #
def _events_context(form, editing=None):
    events = FloodEvent.objects.annotate(n_pred=Count('predictions')).order_by('-date_occurred')
    return {'form': form, 'events': events, 'editing': editing}


@login_required
def events_view(request):
    if request.method == 'POST':
        form = FloodEventForm(request.POST, request.FILES)
        if form.is_valid():
            ev = form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': f'Event "{ev.event_name}" added.'})
            messages.success(request, f'Event "{ev.event_name}" added.')
            return redirect('events')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    else:
        form = FloodEventForm()
    return render(request, 'flood/events.html', _events_context(form))


@login_required
def event_edit_view(request, pk):
    event = get_object_or_404(FloodEvent, pk=pk)
    if request.method == 'POST':
        form = FloodEventForm(request.POST, request.FILES, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, f'Event "{event.event_name}" updated.')
            return redirect('events')
    else:
        form = FloodEventForm(instance=event)
    return render(request, 'flood/events.html', _events_context(form, editing=event))


@login_required
@require_POST
def event_delete_view(request, pk):
    event = get_object_or_404(FloodEvent, pk=pk)
    name = event.event_name
    event.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success', 'message': f'Event "{name}" and its predictions deleted.'})
    messages.success(request, f'Event "{name}" and its predictions deleted.')
    return redirect('events')


@login_required
@require_POST
def prediction_delete_view(request, pk):
    pred = get_object_or_404(FloodPrediction, pk=pk)
    pred.delete()
    messages.success(request, 'Prediction deleted.')
    return redirect('evaluation')


# --------------------------- Drainage Outlets --------------------------- #
def _float(v):
    return float(str(v).strip())


@login_required
def outlets_view(request):
    form = OutletForm()
    if request.method == 'POST':
        if request.FILES.get('csv_file'):
            created = updated = 0
            errors = []
            try:
                text = request.FILES['csv_file'].read().decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(text))
                headers = [(h or '').strip().lower() for h in (reader.fieldnames or [])]
                missing = [c for c in ('name', 'latitude', 'longitude') if c not in headers]
                if missing:
                    raise ValueError('Missing columns: ' + ', '.join(missing))
                for i, raw in enumerate(reader, start=2):
                    row = {(k or '').strip().lower(): v for k, v in raw.items()}
                    try:
                        lat, lon = _float(row['latitude']), _float(row['longitude'])
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            raise ValueError('Coordinates out of range')
                        elev = _float(row.get('elevation') or 0)
                        _, was_created = DrainageOutlet.objects.update_or_create(
                            name=row['name'].strip(),
                            defaults={'latitude': lat, 'longitude': lon, 'elevation': elev},
                        )
                        created += was_created
                        updated += (not was_created)
                    except Exception as exc:
                        errors.append(f'Row {i}: {exc}')
                messages.success(request, f'Outlets imported: {created} new, {updated} updated.')
                if errors:
                    messages.warning(request, f'{len(errors)} row(s) skipped. ' + ' | '.join(errors[:5]))
            except Exception as exc:
                messages.error(request, f'CSV import failed: {exc}')
            return redirect('outlets')

        form = OutletForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Drainage outlet added.')
            return redirect('outlets')
    return render(request, 'flood/outlets.html', {
        'form': form,
        'outlets': DrainageOutlet.objects.order_by('name'),
    })


@login_required
@require_POST
def outlet_delete_view(request, pk):
    outlet = get_object_or_404(DrainageOutlet, pk=pk)
    outlet.delete()
    messages.success(request, 'Drainage outlet deleted.')
    return redirect('outlets')


@login_required
def outlets_template_csv(request):
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="drainage_outlets_template.csv"'
    w = csv.writer(resp)
    w.writerow(['name', 'latitude', 'longitude', 'elevation'])
    w.writerow(['Outlet T-01 Rizal St.', '14.6662', '121.0958', '17.8'])
    w.writerow(['Outlet T-02 Tumana Creek', '14.6641', '121.0985', '16.9'])
    return resp