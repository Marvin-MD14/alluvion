# flood/views_reports.py
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from .models import DrainageOutlet, FloodEvent, FloodPrediction
from .services.ai_model import imagery_label
from .services.evaluation import evaluate_predictions, latest_per_event_and_type
from .services.report import generate_report_pdf


@login_required
def evaluation_view(request):
    predictions = FloodPrediction.objects.select_related('flood_event').order_by('-created_at')
    evaluation_results = evaluate_predictions(predictions)

    context = {
        'rows': evaluation_results['rows'],
        'best': evaluation_results['best'],
        'overall_time': evaluation_results['overall_time'],
        'n_predictions': evaluation_results['n_predictions'],
    }
    return render(request, 'flood/evaluation.html', context)


@login_required
def evaluation_csv(request):
    """I-export ang evaluation table (para sa thesis tables)."""
    ev = evaluate_predictions(FloodPrediction.objects.select_related('flood_event'))
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="alluvion_evaluation.csv"'
    w = csv.writer(resp)
    w.writerow(['imagery_type', 'events', 'precision', 'recall', 'f1_score', 'iou',
                'magnitude_mae_px', 'magnitude_rmse_px', 'magnitude_r2', 'time_mae_hours'])
    for r in ev['rows']:
        w.writerow([r['label'], r['n_events'], r['precision'], r['recall'], r['f1_score'], r['iou'],
                    r['magnitude'].get('mae'), r['magnitude'].get('rmse'), r['magnitude'].get('r2'),
                    r['time'].get('mae_hours')])
    return resp


@login_required
def prediction_detail_view(request, pk):
    prediction = get_object_or_404(FloodPrediction.objects.select_related('flood_event'), pk=pk)
    event = prediction.flood_event
    siblings = latest_per_event_and_type(list(event.predictions.all()))
    siblings.sort(key=lambda p: str(p.imagery_type))

    context = {
        'prediction': prediction,
        'event': event,
        'exp': prediction.explanation or {},
        'imagery_label': imagery_label(prediction.imagery_type),
        'siblings': [{'id': p.id, 'label': imagery_label(p.imagery_type), 'iou': p.iou_score} for p in siblings],
        'extent': prediction.flood_extent_geojson,
        'hazard': prediction.hazard_geojson,
        'reference': event.actual_extent_geojson,
        'outlets': list(DrainageOutlet.objects.values('name', 'latitude', 'longitude', 'elevation')),
    }
    return render(request, 'flood/prediction_detail.html', context)


def _pdf_response(pdf_bytes, name):
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{name}.pdf"'
    return resp


@login_required
def event_report_pdf(request, pk):
    event = get_object_or_404(FloodEvent, pk=pk)
    preds = list(event.predictions.select_related('flood_event'))
    if not preds:
        messages.warning(request, f'Walang prediction pa para sa "{event.event_name}". Patakbuhin muna ang prediction.')
        return redirect('events')
    try:
        pdf = generate_report_pdf(event, preds, outlets=list(DrainageOutlet.objects.all()))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f'Hindi nagawa ang PDF report: {exc}')
        return redirect('events')
    return _pdf_response(pdf, f'alluvion-report-{slugify(event.event_name) or event.pk}')


@login_required
def prediction_report_pdf(request, pk):
    prediction = get_object_or_404(FloodPrediction.objects.select_related('flood_event'), pk=pk)
    event = prediction.flood_event
    try:
        pdf = generate_report_pdf(event, list(event.predictions.all()), primary=prediction,
                                  outlets=list(DrainageOutlet.objects.all()))
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f'Hindi nagawa ang PDF report: {exc}')
        return redirect('prediction_detail', pk=pk)
    return _pdf_response(pdf, f'alluvion-prediction-{prediction.pk}')
