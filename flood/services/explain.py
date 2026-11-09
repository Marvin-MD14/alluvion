"""
Project Alluvion - Explainable AI (XAI).

This is not a black-box model: it uses Otsu thresholding + rainfall-threshold (API).
The "explanation" provides the exact numbers used in the decision, along with plain-language interpretation.
"""
from .ai_model import HAZARD_WEIGHTS, DRAINAGE_FULL_DISTANCE_M, imagery_label


def build_explanation(sar, time_res, imagery_type, metrics, warnings=None):
    stats = sar['stats']
    thr = sar['threshold_used']
    label = imagery_label(imagery_type)

    bullets = []
    
    # 1. Threshold explanation
    bullets.append(
        f"Pixels with backscatter lower than {thr:.2f} dB (Otsu threshold) were classified as water. "
        f"Calm water reflects radar away from the sensor (specular reflection), making it appear dark in SAR imagery."
    )
    
    # 2. Backscatter means
    if stats['mean_flood_db'] is not None and stats['mean_land_db'] is not None:
        bullets.append(
            f"Average backscatter of the flood class: {stats['mean_flood_db']:.2f} dB; land class: "
            f"{stats['mean_land_db']:.2f} dB (gap: {stats['mean_land_db'] - stats['mean_flood_db']:.2f} dB)."
        )
        
    # 3. Separability
    sep = stats['separability']
    if sep is not None:
        quality = 'clear' if sep >= 0.7 else ('moderate' if sep >= 0.5 else 'weak')
        bullets.append(
            f"Class separability (between-class variance / total variance) = {sep:.2f} -> {quality} separation "
            f"between the water and land histograms; "
            + ("the threshold is reliable." if sep >= 0.5 else "caution: the bimodal histogram is not distinct, "
               "the threshold may be inaccurate.")
        )
        
    # 4. Urban warning
    if 'URBAN' in (imagery_type or '').upper():
        bullets.append(
            "In urban areas, 'double-bounce' from buildings may mask floodwater (false negatives); "
            "expect lower recall for this imagery type."
        )

    # 5. Time / Rainfall explanation
    t = time_res or {}
    time_block = None
    if t.get('predicted_time') is not None or t.get('note'):
        time_block = {
            'model': 'Antecedent Precipitation Index (API) rainfall-threshold',
            'decay': 0.85,
            'threshold_mm': t.get('threshold_mm'),
            'calibrated_from': t.get('calibrated_from'),
            'crossing_date': t.get('crossing_date'),
            'fallback': t.get('fallback'),
            'contributions': t.get('contributions', []),
            'series': t.get('series', []),
            'note': t.get('note', ''),
        }
        if t.get('predicted_time') is not None and not t.get('fallback'):
            top = max(t['contributions'], key=lambda c: c['share_pct']) if t.get('contributions') else None
            bullets.append(
                f"Flood timing: API exceeded {t['threshold_mm']} mm on {t['crossing_date']}"
                + (f"; the highest daily rainfall contribution was on {top['date']} ({top['share_pct']}%)." if top else ".")
            )
        elif t.get('note'):
            bullets.append(t['note'])

    # 6. Hazard levels
    hz = sar.get('hazard_counts', {})
    hazard_block = {
        'low_px': hz.get('low', 0), 'moderate_px': hz.get('moderate', 0), 'high_px': hz.get('high', 0),
        'weights': HAZARD_WEIGHTS, 'drainage_full_distance_m': DRAINAGE_FULL_DISTANCE_M,
    }
    bullets.append(
        f"Hazard level = {int(HAZARD_WEIGHTS['backscatter_margin']*100)}% backscatter margin depth + "
        f"{int(HAZARD_WEIGHTS['drainage_distance']*100)}% distance to the nearest drainage outlet "
        f"(Low < 0.40, Moderate < 0.70, High >= 0.70)."
    )
    
    # 7. Preprocessing
    if sar.get('units_note'):
        bullets.append(
            f"Preprocessing: nodata masking, {sar['units_note']}, 3x3 median speckle filter, "
            f"removal of small (<9 px) noise."
        )
        
    # 8. Warnings
    for w in (warnings or []):
        bullets.append(f"Note: {w}")

    return {
        'method': 'Otsu global thresholding on SAR backscatter (dB)',
        'imagery_type': label,
        'sar': {
            'threshold_db': round(thr, 3),
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()},
            'histogram': sar['histogram'],
        },
        'time': time_block,
        'hazard': hazard_block,
        'metrics': metrics,
        'summary': bullets,
    }