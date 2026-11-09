# flood/services/pipeline.py
"""
Pipeline: para sa isang FloodEvent, patakbuhin ang SAR analysis sa bawat imagery type
(VH Linear / VH Gamma / VV Linear / VV Gamma / SAR Urban), kunin ang metrics laban sa ground truth,
hulaan ang oras ng baha (rainfall API model), gumawa ng XAI explanation, at i-save ang FloodPrediction.
"""
import json
import math
import os
from datetime import datetime, time as dtime, timedelta

import numpy as np
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from satellite.models import SatelliteImage

from ..models import DrainageOutlet, FloodPrediction
from . import time_model
from .ai_model import (flood_extent_geojson, hazard_geojson, normalize_imagery_type,
                       process_sar_image, rasterize_reference)
from .evaluation import magnitude_metrics, pixel_metrics
from .explain import build_explanation

# Sentinel-1 revisit ~6-12 araw: pumili ng images na malapit sa petsa ng event
IMAGE_WINDOW_DAYS = 7


def _sanitize(obj):
    """JSON-safe: numpy -> python, NaN/inf -> None, datetime -> iso."""
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _sanitize(obj.tolist())
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    return str(obj)


def _aware(dt):
    return timezone.make_aware(dt) if getattr(settings, 'USE_TZ', False) and timezone.is_naive(dt) else dt


def select_images(event, only_image=None):
    """Returns (images, messages). Isang image (pinakamalapit sa petsa) kada imagery type."""
    if only_image is not None:
        return [only_image], []
    window = timedelta(days=IMAGE_WINDOW_DAYS)
    qs = SatelliteImage.objects.filter(
        acquisition_date__range=(event.date_occurred - window, event.date_occurred + window))
    best = {}
    for img in qs:
        code = normalize_imagery_type(img.imagery_type) or img.imagery_type
        key = (abs((img.acquisition_date - event.date_occurred).days), -img.id)
        if code not in best or key < best[code][0]:
            best[code] = (key, img)
    images = [v[1] for v in best.values()]
    if not images:
        return [], [f'Walang Sentinel-1 image na na-acquire sa loob ng +/-{IMAGE_WINDOW_DAYS} araw ng '
                    f'{event.date_occurred}. Mag-upload muna sa "Upload SAR" page (tamang acquisition date).']
    images.sort(key=lambda i: str(normalize_imagery_type(i.imagery_type) or i.imagery_type))
    return images, []


def run_all_for_event(event, only_image=None):
    predictions, messages = [], []
    images, msgs = select_images(event, only_image)
    messages.extend(msgs)
    if not images:
        return [], messages

    outlets = list(DrainageOutlet.objects.values_list('longitude', 'latitude'))
    if not outlets:
        messages.append('Walang drainage outlets - idagdag sa "Drainage Outlets" page para magamit sa hazard map.')

    try:
        time_res = time_model.predict_flood_time(event)
    except Exception as exc:  # noqa: BLE001
        time_res = None
        messages.append(f'Hindi nagawa ang flood-time prediction: {exc}')

    predicted_time = (time_res or {}).get('predicted_time')
    warnings = []
    if predicted_time is None:
        predicted_time = _aware(datetime.combine(event.date_occurred, dtime(12, 0)))
        warnings.append('Walang rainfall data - ang predicted time ay placeholder (12:00 ng petsa ng event).')
        messages.append('Walang PAGASA rainfall para sa event na ito; placeholder ang predicted time. '
                        'Mag-upload ng weather CSV sa "Weather Data" page.')
    time_err = time_model.time_error_hours(predicted_time, event.actual_flood_time)

    for img in images:
        label = normalize_imagery_type(img.imagery_type) or img.imagery_type
        try:
            path = img.file.path
        except Exception:  # noqa: BLE001
            path = None
        if not path or not os.path.exists(path):
            messages.append(f'{label}: hindi makita ang file sa disk.')
            continue

        sar = process_sar_image(path, outlets=outlets)
        if 'error' in sar:
            messages.append(f'{label}: {sar["error"]}')
            continue

        ref_mask = None
        if event.actual_extent_geojson:
            ref_mask = rasterize_reference(event.actual_extent_geojson, sar['shape'], sar['transform'], sar['crs'])
            if ref_mask is None:
                messages.append(f'{label}: hindi magamit ang reference GeoJSON (walang Polygon).')

        loc = pixel_metrics(sar['mask'], ref_mask, sar['valid']) if ref_mask is not None else \
            {'precision': None, 'recall': None, 'f1_score': None, 'iou': None}

        actual_px = event.actual_magnitude_pixels
        if actual_px is None and ref_mask is not None:
            actual_px = int((ref_mask & sar['valid']).sum())
        mag = magnitude_metrics([actual_px], [sar['flood_pixels']]) if actual_px is not None else {}

        metrics = {'location': loc, 'magnitude': mag, 'time_error_hours': time_err,
                   'actual_magnitude_pixels': actual_px}
        explanation = _sanitize(build_explanation(sar, time_res, label, metrics, warnings))

        try:
            with transaction.atomic():
                pred = FloodPrediction.objects.create(
                    flood_event=event,
                    satellite_image=img,
                    imagery_type=label,
                    predicted_time=predicted_time,
                    predicted_magnitude_pixels=sar['flood_pixels'],
                    flood_percentage=sar['percentage'],
                    total_land_pixels=sar['total_land_pixels'],
                    precision=loc.get('precision'),
                    recall=loc.get('recall'),
                    f1_score=loc.get('f1_score'),
                    iou_score=loc.get('iou'),
                    time_error_hours=None if time_err is None else round(time_err, 2),
                    flood_extent_geojson=flood_extent_geojson(sar),
                    hazard_geojson=hazard_geojson(sar),
                    explanation=explanation,
                )
                if not img.is_processed:
                    img.is_processed = True
                    img.save(update_fields=['is_processed'])
            predictions.append(pred)
        except Exception as exc:  # noqa: BLE001
            messages.append(f'{label}: hindi ma-save ang prediction ({exc}).')

    return predictions, messages
