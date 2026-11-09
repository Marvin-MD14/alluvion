"""
Project Alluvion - AI / SAR processing core (Sentinel-1 flood detection).

Pipeline (para sa isang GeoTIFF):
  1. Basahin ang band 1, i-mask ang nodata / invalid pixels.
  2. Kung linear ang values (VH/VV Linear) -> i-convert sa dB (10*log10); kung dB na, gamitin as-is.
  3. 3x3 median filter (speckle reduction).
  4. Otsu global threshold sa backscatter histogram -> water (flood) pixels = dB < threshold.
  5. Alisin ang maliliit na (< 9 px) na noise.
  6. Hazard level (Low / Moderate / High) para sa bawat flood pixel:
        score = 0.60 * backscatter_margin + 0.40 * layo_sa_pinakamalapit_na_drainage_outlet
     (kung walang outlets, backscatter margin lang ang gamit).
  7. Output: masks, GeoJSON (extent + hazard), at "XAI stats" (threshold, histogram, separability).
"""
import json
import math
import re

import numpy as np
import rasterio
from rasterio import features
from rasterio.warp import transform as warp_transform, transform_geom
from scipy import ndimage

IMAGERY_CODES = ['VH_LINEAR', 'VH_GAMMA', 'VV_LINEAR', 'VV_GAMMA', 'SAR_URBAN']
IMAGERY_LABELS = {
    'VH_LINEAR': 'VH Linear',
    'VH_GAMMA': 'VH Gamma',
    'VV_LINEAR': 'VV Linear',
    'VV_GAMMA': 'VV Gamma',
    'SAR_URBAN': 'SAR Urban',
}

HAZARD_WEIGHTS = {'backscatter_margin': 0.6, 'drainage_distance': 0.4}
DRAINAGE_FULL_DISTANCE_M = 500.0      # layo (m) mula sa outlet na itinuturing na "buong" hazard contribution
HAZARD_BREAKS = (0.40, 0.70)          # Low < 0.40 <= Moderate < 0.70 <= High
HAZARD_LABELS = {1: 'Low', 2: 'Moderate', 3: 'High'}
MIN_COMPONENT_PX = 9
HIST_BINS = 40


# ----------------------------------------------------------------------------- #
# imagery type helpers
# ----------------------------------------------------------------------------- #
def normalize_imagery_type(value):
    """'VH Linear' / 'vh_linear' / 'VH-LINEAR' -> 'VH_LINEAR'. None kung hindi kilala."""
    if not value:
        return None
    s = re.sub(r'[^A-Z0-9]+', '_', str(value).upper()).strip('_')
    if s in IMAGERY_CODES:
        return s
    compact = s.replace('_', '')
    for code in IMAGERY_CODES:
        if code.replace('_', '') == compact:
            return code
    return None


def imagery_label(value):
    code = normalize_imagery_type(value)
    if code:
        return IMAGERY_LABELS[code]
    return str(value) if value else 'Unknown'


# ----------------------------------------------------------------------------- #
# geometry helpers
# ----------------------------------------------------------------------------- #
def _is_wgs84(crs):
    if crs is None:
        return True
    try:
        return crs.to_epsg() == 4326
    except Exception:
        return False


def _is_projected(crs):
    return crs is not None and bool(getattr(crs, 'is_projected', False)) and not _is_wgs84(crs)


def _round_coords(c, nd=6):
    if isinstance(c, (list, tuple)):
        if c and isinstance(c[0], (int, float)):
            return [round(float(x), nd) for x in c]
        return [_round_coords(x, nd) for x in c]
    return c


def raster_to_geojson(arr, transform, crs=None, class_labels=None):
    """Integer raster (0 = background) -> GeoJSON FeatureCollection (EPSG:4326 / lon-lat)."""
    arr = np.asarray(arr).astype('uint8')
    labels = class_labels or {}
    reproject = crs is not None and not _is_wgs84(crs)
    feats = []
    for geom, val in features.shapes(arr, mask=arr > 0, transform=transform):
        if reproject:
            geom = transform_geom(crs, 'EPSG:4326', geom)
        v = int(val)
        feats.append({
            'type': 'Feature',
            'properties': {'value': v, 'level': labels.get(v, str(v))},
            'geometry': {'type': geom['type'], 'coordinates': _round_coords(geom['coordinates'])},
        })
    return {'type': 'FeatureCollection', 'features': feats}


def rasterize_reference(geojson, shape, transform, crs=None):
    """Reference flood extent (GeoJSON, lon-lat) -> bool mask na kapareho ng grid ng SAR image."""
    if not geojson:
        return None
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except ValueError:
            return None
    t = geojson.get('type')
    if t == 'FeatureCollection':
        geoms = [f.get('geometry') for f in geojson.get('features', [])]
    elif t == 'Feature':
        geoms = [geojson.get('geometry')]
    else:
        geoms = [geojson]
    geoms = [g for g in geoms if g and g.get('type') in ('Polygon', 'MultiPolygon')]
    if not geoms:
        return None
    if crs is not None and not _is_wgs84(crs):
        geoms = [transform_geom('EPSG:4326', crs, g) for g in geoms]
    out = features.rasterize([(g, 1) for g in geoms], out_shape=tuple(shape), transform=transform,
                             fill=0, dtype='uint8')
    return out.astype(bool)


# ----------------------------------------------------------------------------- #
# SAR processing
# ----------------------------------------------------------------------------- #
def otsu_threshold(values, bins=256):
    """Returns (threshold, separability). separability = between-class variance / total variance."""
    v = np.asarray(values, dtype='float64')
    v = v[np.isfinite(v)]
    if v.size == 0:
        return 0.0, 0.0
    lo, hi = np.percentile(v, [0.5, 99.5])
    if hi <= lo:
        return float(np.median(v)), 0.0
    hist, edges = np.histogram(np.clip(v, lo, hi), bins=bins, range=(lo, hi))
    p = hist.astype('float64') / hist.sum()
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(p)
    w1 = 1.0 - w0
    mu = np.cumsum(p * centers)
    mu_t = mu[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        between = (mu_t * w0 - mu) ** 2 / (w0 * w1)
    between = np.nan_to_num(between, nan=0.0, posinf=0.0, neginf=0.0)
    k = int(np.argmax(between))
    thr = float(edges[k + 1])
    total_var = float(np.sum(p * (centers - mu_t) ** 2))
    sep = float(between[k] / total_var) if total_var > 0 else 0.0
    return thr, float(min(max(sep, 0.0), 1.0))


def _min_distance_m(xs, ys, outlets, crs):
    """Pinakamalapit na outlet (meters) para sa bawat (x, y) pixel center."""
    pts = np.asarray(outlets, dtype='float64').reshape(-1, 2)   # (lon, lat)
    best = np.full(xs.shape, np.inf)
    if _is_projected(crs):
        ox, oy = warp_transform('EPSG:4326', crs, pts[:, 0].tolist(), pts[:, 1].tolist())
        for a, b in zip(ox, oy):
            best = np.minimum(best, np.hypot(xs - a, ys - b))
        return best
    for lon, lat in pts:
        dx = (xs - lon) * 111320.0 * np.cos(np.radians((ys + lat) / 2.0))
        dy = (ys - lat) * 110540.0
        best = np.minimum(best, np.hypot(dx, dy))
    return best


def _hazard_levels(db, mask, thr, outlets, transform, crs):
    """Returns (hazard uint8 array 0..3, counts dict, note)."""
    hazard = np.zeros(mask.shape, dtype='uint8')
    counts = {'low': 0, 'moderate': 0, 'high': 0}
    if not mask.any():
        return hazard, counts, 'Walang flood pixels na natukoy.'
    rr, cc = np.nonzero(mask)
    vals = db[rr, cc]
    lo = float(np.percentile(vals, 2))
    margin = np.clip((thr - vals) / max(thr - lo, 1e-6), 0.0, 1.0)

    note = ''
    if outlets is not None and len(outlets) > 0:
        xs = transform.c + (cc + 0.5) * transform.a + (rr + 0.5) * transform.b
        ys = transform.f + (cc + 0.5) * transform.d + (rr + 0.5) * transform.e
        dist = np.clip(_min_distance_m(xs, ys, outlets, crs) / DRAINAGE_FULL_DISTANCE_M, 0.0, 1.0)
        score = HAZARD_WEIGHTS['backscatter_margin'] * margin + HAZARD_WEIGHTS['drainage_distance'] * dist
    else:
        score = margin
        note = 'Walang drainage outlets sa database; backscatter margin lang ang ginamit sa hazard level.'

    level = np.where(score < HAZARD_BREAKS[0], 1, np.where(score < HAZARD_BREAKS[1], 2, 3)).astype('uint8')
    hazard[rr, cc] = level
    bc = np.bincount(level, minlength=4)
    counts = {'low': int(bc[1]), 'moderate': int(bc[2]), 'high': int(bc[3])}
    return hazard, counts, note


def process_sar_image(path, outlets=None):
    """
    Returns dict (may contain 'error'). outlets = list ng (lon, lat).
    Keys: mask, valid, shape, transform, crs, flood_pixels, total_land_pixels, percentage,
          threshold_used, stats, histogram, hazard, hazard_counts, units_note, hazard_note
    """
    try:
        with rasterio.open(path) as src:
            arr = src.read(1).astype('float64')
            nodata = src.nodata
            transform = src.transform
            crs = src.crs
    except Exception as exc:  # noqa: BLE001
        return {'error': f'Hindi mabasa ang GeoTIFF: {exc}'}

    valid = np.isfinite(arr)
    if nodata is not None and np.isfinite(nodata):
        valid &= arr != nodata
    vals = arr[valid]
    if vals.size == 0:
        return {'error': 'Walang valid pixels sa image (lahat nodata).'}

    is_linear = bool(vals.min() >= 0 and np.percentile(vals, 99) <= 10)
    if is_linear:
        valid &= arr > 0
        db = 10.0 * np.log10(np.where(valid, arr, 1.0))
        units_note = 'linear backscatter na-convert sa dB (10*log10)'
    else:
        db = arr.copy()
        units_note = 'backscatter na nasa dB na'
    valid &= (db > -60) & (db < 40)
    if valid.sum() < 100:
        return {'error': 'Masyadong kaunti ang valid pixels para ma-analyze.'}

    # speckle filter
    fill = float(np.median(db[valid]))
    smooth = ndimage.median_filter(np.where(valid, db, fill), size=3)
    db = np.where(valid, smooth, fill)

    thr, sep = otsu_threshold(db[valid])
    mask = valid & (db < thr)

    # alisin ang maliliit na noise
    lab, n = ndimage.label(mask)
    if n:
        sizes = np.bincount(lab.ravel())
        small = sizes < MIN_COMPONENT_PX
        small[0] = False
        mask &= ~small[lab]

    flood_px = int(mask.sum())
    total_px = int(valid.sum())
    flood_vals = db[mask]
    land_vals = db[valid & ~mask]

    def _mean(a):
        return float(a.mean()) if a.size else None

    def _std(a):
        return float(a.std()) if a.size else None

    stats = {
        'mean_flood_db': _mean(flood_vals),
        'mean_land_db': _mean(land_vals),
        'std_flood_db': _std(flood_vals),
        'std_land_db': _std(land_vals),
        'separability': float(sep),
        'bimodal_ok': bool(sep >= 0.5),
        'n_valid_pixels': total_px,
    }

    v = db[valid]
    h_lo, h_hi = np.percentile(v, [0.5, 99.5])
    if h_hi <= h_lo:
        h_hi = h_lo + 1.0
    counts, edges = np.histogram(np.clip(v, h_lo, h_hi), bins=HIST_BINS, range=(h_lo, h_hi))
    histogram = {'bin_edges': [round(float(e), 3) for e in edges], 'counts': [int(c) for c in counts]}

    hazard, hz_counts, hz_note = _hazard_levels(db, mask, thr, outlets, transform, crs)

    return {
        'mask': mask,
        'valid': valid,
        'shape': mask.shape,
        'transform': transform,
        'crs': crs,
        'flood_pixels': flood_px,
        'total_land_pixels': total_px,
        'percentage': round(100.0 * flood_px / total_px, 2) if total_px else 0.0,
        'threshold_used': float(thr),
        'stats': stats,
        'histogram': histogram,
        'hazard': hazard,
        'hazard_counts': hz_counts,
        'units_note': units_note,
        'hazard_note': hz_note,
    }


def flood_extent_geojson(sar):
    return raster_to_geojson(sar['mask'].astype('uint8'), sar['transform'], sar['crs'], {1: 'Flooded'})


def hazard_geojson(sar):
    return raster_to_geojson(sar['hazard'], sar['transform'], sar['crs'], HAZARD_LABELS)
