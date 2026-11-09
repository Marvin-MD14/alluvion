"""
Project Alluvion - Flood occurrence time prediction.

Rainfall-threshold model gamit ang Antecedent Precipitation Index (API) mula sa PAGASA daily rainfall:

    API_t = DECAY * API_(t-1) + rain_t

Kapag lumampas ang API sa threshold, "lumilitaw" ang baha. Ang oras sa loob ng araw ay tinatantya
sa pamamagitan ng pag-assume na pantay ang buhos ng ulan sa buong araw. Ang threshold ay
kina-calibrate mula sa ibang historical events (leave-one-out, para hindi "nandaya" ang evaluation).
"""
import statistics
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Avg
from django.utils import timezone

from weather.models import WeatherRecord

DECAY = 0.85
SPINUP_DAYS = 14
DAYS_BEFORE = 7
DAYS_AFTER = 1
DEFAULT_THRESHOLD_MM = 120.0
MIN_EVENTS_FOR_CALIBRATION = 2


def _aware(naive_dt):
    if getattr(settings, 'USE_TZ', False):
        return timezone.make_aware(naive_dt)
    return naive_dt


def _local(dt):
    if dt is not None and getattr(settings, 'USE_TZ', False) and timezone.is_aware(dt):
        return timezone.localtime(dt)
    return dt


def daily_rainfall(start, end):
    """dict {date: rainfall_mm} (average kung maraming station)."""
    qs = (WeatherRecord.objects.filter(date_recorded__range=(start, end))
          .values('date_recorded').annotate(r=Avg('rainfall_mm')))
    return {row['date_recorded']: float(row['r']) for row in qs}


def api_series(rain, first_day, last_day):
    """List ng dict per day: date, rain, api_prev (na-decay na), api."""
    day = first_day - timedelta(days=SPINUP_DAYS)
    api = 0.0
    out = []
    while day <= last_day:
        r = rain.get(day, 0.0)
        prev = DECAY * api
        api = prev + r
        if day >= first_day:
            out.append({'date': day, 'rain_mm': r, 'api_prev': prev, 'api': api})
        day += timedelta(days=1)
    return out


def calibrate_threshold(exclude_event_id=None):
    """Median ng API sa mismong actual flood time ng ibang events."""
    from flood.models import FloodEvent

    values = []
    qs = FloodEvent.objects.exclude(actual_flood_time__isnull=True)
    if exclude_event_id:
        qs = qs.exclude(id=exclude_event_id)
    for ev in qs:
        t = _local(ev.actual_flood_time)
        day = t.date()
        rain = daily_rainfall(day - timedelta(days=SPINUP_DAYS), day)
        if not rain:
            continue
        row = api_series(rain, day, day)[0]
        frac = (t.hour + t.minute / 60) / 24
        values.append(row['api_prev'] + row['rain_mm'] * frac)
    if len(values) >= MIN_EVENTS_FOR_CALIBRATION:
        return float(statistics.median(values)), len(values)
    return DEFAULT_THRESHOLD_MM, 0


def predict_flood_time(event):
    """
    Returns dict:
      predicted_time (aware datetime), threshold_mm, calibrated_from, fallback (bool),
      crossing_date, series, contributions, note
    """
    # date_occurred lang ang gamit bilang hangganan ng pagtingin; HINDI ginagamit ang actual_flood_time
    # sa mismong prediction (para walang data leakage).
    ref_day = event.date_occurred
    first = ref_day - timedelta(days=DAYS_BEFORE)
    last = ref_day + timedelta(days=DAYS_AFTER)

    threshold, n_cal = calibrate_threshold(exclude_event_id=event.id)
    rain = daily_rainfall(first - timedelta(days=SPINUP_DAYS), last)
    if not any(rain.get(first + timedelta(days=i), 0) for i in range((last - first).days + 1)):
        return {
            'predicted_time': None, 'threshold_mm': threshold, 'calibrated_from': n_calibration_label(n_cal),
            'fallback': True, 'crossing_date': None, 'series': [], 'contributions': [],
            'note': 'Walang PAGASA rainfall records para sa panahon ng event - mag-upload ng weather CSV.',
        }

    series = api_series(rain, first, last)
    crossing = next((row for row in series if row['api'] >= threshold), None)
    fallback = crossing is None
    if fallback:
        crossing = max(series, key=lambda r: r['rain_mm'])
        predicted = _aware(datetime.combine(crossing['date'], datetime.min.time()) + timedelta(hours=12))
        note = ('Hindi lumampas ang API sa threshold; ginamit ang araw na may pinakamalakas na ulan '
                '(12:00) bilang fallback.')
    else:
        need = threshold - crossing['api_prev']
        frac = min(max(need / crossing['rain_mm'], 0.02), 1.0) if crossing['rain_mm'] > 0 else 0.5
        predicted = _aware(datetime.combine(crossing['date'], datetime.min.time()) + timedelta(hours=24 * frac))
        note = ''

    # contributions: gaano kalaki ang naitulong ng ulan ng bawat araw sa API sa crossing day
    contributions = []
    cdate = crossing['date']
    frac_today = 1.0 if fallback else min(max((threshold - crossing['api_prev']) / max(crossing['rain_mm'], 1e-9), 0.02), 1.0)
    for k in range(0, 8):
        d = cdate - timedelta(days=k)
        r = rain.get(d, 0.0)
        weight = DECAY ** k
        effective = r * weight * (frac_today if k == 0 else 1.0)
        contributions.append({'date': d.isoformat(), 'rain_mm': round(r, 1), 'weight': round(weight, 3),
                              'contribution_mm': round(effective, 1)})
    total = sum(c['contribution_mm'] for c in contributions) or 1.0
    for c in contributions:
        c['share_pct'] = round(100 * c['contribution_mm'] / total, 1)

    return {
        'predicted_time': predicted,
        'threshold_mm': round(threshold, 1),
        'calibrated_from': n_calibration_label(n_cal),
        'fallback': fallback,
        'crossing_date': cdate.isoformat(),
        'series': [{'date': r['date'].isoformat(), 'rain_mm': round(r['rain_mm'], 1), 'api': round(r['api'], 1)}
                   for r in series],
        'contributions': contributions,
        'note': note,
    }


def n_calibration_label(n):
    return f'{n} historical event(s)' if n else 'default threshold (kulang ang historical events)'


def time_error_hours(predicted, actual):
    if predicted is None or actual is None:
        return None
    return abs((predicted - actual).total_seconds()) / 3600.0
