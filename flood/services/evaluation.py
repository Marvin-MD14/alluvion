# flood/services/evaluation.py
import math
import numpy as np
from ..models import FloodPrediction # <-- TAMA ITO
from .ai_model import IMAGERY_CODES, IMAGERY_LABELS, normalize_imagery_type

def pixel_metrics(pred_mask, ref_mask, valid_mask=None):
    # ... (panatilihin ang dati mong logic)
    if ref_mask is None:
        return {'precision': None, 'recall': None, 'f1_score': None, 'iou': None}
    pred = pred_mask.astype(bool)
    ref = ref_mask.astype(bool)
    if valid_mask is not None:
        pred = pred & valid_mask
        ref = ref & valid_mask
    if ref.sum() == 0:
        return {'precision': None, 'recall': None, 'f1_score': None, 'iou': None}
    tp = int(np.sum(pred & ref))
    fp = int(np.sum(pred & ~ref))
    fn = int(np.sum(~pred & ref))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    union = tp + fp + fn
    iou = tp / union if union else 0.0
    return {'precision': round(precision, 4), 'recall': round(recall, 4),
            'f1_score': round(f1, 4), 'iou': round(iou, 4)}

def magnitude_metrics(actual, predicted):
    # ... (panatilihin)
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if a.size == 0:
        return {'mae': None, 'rmse': None, 'r2': None, 'n': 0}
    err = p - a
    mae = float(np.mean(np.abs(err)))
    rmse = float(math.sqrt(np.mean(err ** 2)))
    r2 = None
    if a.size >= 2:
        ss_tot = float(np.sum((a - a.mean()) ** 2))
        if ss_tot > 0:
            r2 = float(1 - np.sum(err ** 2) / ss_tot)
    return {'mae': round(mae, 2), 'rmse': round(rmse, 2),
            'r2': round(r2, 4) if r2 is not None else None, 'n': int(a.size)}

def time_metrics(errors_hours):
    e = [x for x in errors_hours if x is not None]
    if not e:
        return {'mae_hours': None, 'min_hours': None, 'max_hours': None, 'n': 0}
    return {'mae_hours': round(float(np.mean(e)), 2), 'min_hours': round(float(min(e)), 2),
            'max_hours': round(float(max(e)), 2), 'n': len(e)}

def latest_per_event_and_type(predictions):
    latest = {}
    for p in predictions:
        key = (p.flood_event_id, normalize_imagery_type(p.imagery_type) or p.imagery_type)
        if key not in latest or p.created_at > latest[key].created_at:
            latest[key] = p
    return list(latest.values())

def _mean(values):
    v = [x for x in values if x is not None]
    return round(float(np.mean(v)), 4) if v else None

def evaluate_predictions(predictions):
    preds = latest_per_event_and_type(list(predictions))
    by_type = {}
    for p in preds:
        code = normalize_imagery_type(p.imagery_type) or (p.imagery_type or 'UNKNOWN')
        by_type.setdefault(code, []).append(p)

    rows = []
    for code in list(IMAGERY_CODES) + [c for c in by_type if c not in IMAGERY_CODES]:
        items = by_type.get(code)
        if not items:
            continue
        mag_pairs = [(p.flood_event.actual_magnitude_pixels, p.predicted_magnitude_pixels)
                     for p in items if p.flood_event.actual_magnitude_pixels is not None]
        mag = magnitude_metrics([a for a, _ in mag_pairs], [b for _, b in mag_pairs])
        tm = time_metrics([p.time_error_hours for p in items])
        rows.append({
            'code': code,
            'label': IMAGERY_LABELS.get(code, code),
            'n_events': len(items),
            'precision': _mean(p.precision for p in items),
            'recall': _mean(p.recall for p in items),
            'f1_score': _mean(p.f1_score for p in items),
            'iou': _mean(p.iou_score for p in items),
            'time': tm,
            'magnitude': mag,
        })

    ranked = [r for r in rows if r['iou'] is not None]
    best = max(ranked, key=lambda r: r['iou']) if ranked else None

    per_event_time = {}
    for p in preds:
        per_event_time.setdefault(p.flood_event_id, p.time_error_hours)
    overall_time = time_metrics(list(per_event_time.values()))

    return {'rows': rows, 'best': best, 'overall_time': overall_time, 'n_predictions': len(preds)}