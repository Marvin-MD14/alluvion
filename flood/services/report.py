"""
Project Alluvion - Digital PDF Report (OUTPUT ng IPO model):
Flood Extent Map, Flood Hazard Map, Total Classified Flood Pixels, % of Flood Pixels vs Total Land Pixels,
+ evaluation (time, magnitude, location) at XAI explanation.
"""
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path  # noqa: E402
from django.utils import timezone  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,  # noqa: E402
                                TableStyle)

from .ai_model import imagery_label  # noqa: E402
from .evaluation import evaluate_predictions, latest_per_event_and_type  # noqa: E402

BLUE = colors.HexColor('#0066cc')
HAZARD_COLORS = {'Low': '#fde047', 'Moderate': '#fb923c', 'High': '#dc2626'}


# ----------------------------- plotting helpers ----------------------------- #
def _polygon_paths(geom):
    """GeoJSON Polygon/MultiPolygon -> list ng matplotlib PathPatch vertices/codes."""
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    out = []
    for poly in polys:
        verts, codes = [], []
        for ring in poly:
            ring = np.asarray(ring)
            verts.extend(ring.tolist())
            codes.extend([Path.MOVETO] + [Path.LINETO] * (len(ring) - 2) + [Path.CLOSEPOLY])
        out.append(Path(verts, codes))
    return out


def _draw_geojson(ax, geojson, facecolor, alpha=0.6, edgecolor='none', color_by=None):
    if not geojson:
        return
    for f in geojson.get('features', []):
        g = f.get('geometry')
        if not g:
            continue
        fc = facecolor
        if color_by:
            fc = color_by.get(f.get('properties', {}).get('level'), facecolor)
        for path in _polygon_paths(g):
            ax.add_patch(PathPatch(path, facecolor=fc, edgecolor=edgecolor, linewidth=0.2, alpha=alpha))


def _bounds(*geojsons):
    xs, ys = [], []
    for gj in geojsons:
        if not gj:
            continue
        for f in gj.get('features', []):
            g = f.get('geometry')
            if not g:
                continue
            for path in _polygon_paths(g):
                v = path.vertices
                xs.extend(v[:, 0]); ys.extend(v[:, 1])
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def _fig_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _map_figure(event, pred, outlets, mode):
    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    b = _bounds(pred.flood_extent_geojson, event.actual_extent_geojson)
    ax.set_facecolor('#f1f5f9')
    if mode == 'extent':
        if event.actual_extent_geojson:
            _draw_geojson(ax, event.actual_extent_geojson, '#2563eb', alpha=0.35)
        _draw_geojson(ax, pred.flood_extent_geojson, '#dc2626', alpha=0.55)
        handles = [plt.Rectangle((0, 0), 1, 1, fc='#dc2626', alpha=0.55, label='Predicted flood extent')]
        if event.actual_extent_geojson:
            handles.append(plt.Rectangle((0, 0), 1, 1, fc='#2563eb', alpha=0.35, label='Reference (actual) extent'))
        ax.set_title('Flood Extent Map - predicted vs reference', fontsize=11)
    else:
        _draw_geojson(ax, pred.hazard_geojson, '#dc2626', alpha=0.85, color_by=HAZARD_COLORS)
        handles = [plt.Rectangle((0, 0), 1, 1, fc=c, label=f'{k} hazard') for k, c in HAZARD_COLORS.items()]
        ax.set_title('Flood Hazard Map (Low / Moderate / High)', fontsize=11)
    if outlets:
        ax.scatter([o.longitude for o in outlets], [o.latitude for o in outlets], marker='^', s=38,
                   c='#0f172a', zorder=5, label='Drainage outlet')
        handles.append(plt.Line2D([], [], marker='^', ls='', c='#0f172a', label='Drainage outlet'))
    if b:
        padx, pady = (b[1] - b[0]) * 0.05, (b[3] - b[2]) * 0.05
        ax.set_xlim(b[0] - padx, b[1] + padx)
        ax.set_ylim(b[2] - pady, b[3] + pady)
        ax.set_aspect(1 / np.cos(np.deg2rad((b[2] + b[3]) / 2)))
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    ax.ticklabel_format(useOffset=False, style='plain')
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.yaxis.set_major_locator(MaxNLocator(6))
    ax.tick_params(labelsize=7)
    ax.legend(handles=handles, loc='lower left', fontsize=7, framealpha=0.9)
    ax.grid(alpha=0.25, lw=0.4)
    return _fig_bytes(fig)


def _histogram_figure(pred):
    sar = (pred.explanation or {}).get('sar')
    if not sar:
        return None
    h = sar['histogram']
    edges = np.asarray(h['bin_edges']); counts = np.asarray(h['counts'])
    centers = (edges[:-1] + edges[1:]) / 2
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    ax.bar(centers, counts, width=np.diff(edges), color='#94a3b8', edgecolor='white', lw=0.3)
    ax.axvline(sar['threshold_db'], color='#dc2626', lw=1.6, label=f"Otsu threshold = {sar['threshold_db']:.2f} dB")
    ax.set_xlabel('Backscatter (dB)'); ax.set_ylabel('Pixels')
    ax.set_title('Backscatter histogram and decision threshold', fontsize=10)
    ax.legend(fontsize=8)
    ax.tick_params(labelsize=7)
    return _fig_bytes(fig)


def _rainfall_figure(pred):
    t = (pred.explanation or {}).get('time')
    if not t or not t.get('series'):
        return None
    s = t['series']
    labels = [r['date'][5:] for r in s]
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    ax.bar(labels, [r['rain_mm'] for r in s], color='#60a5fa', label='Daily rainfall (mm)')
    ax2 = ax.twinx()
    ax2.plot(labels, [r['api'] for r in s], color='#0f172a', marker='o', ms=3, label='API (mm)')
    if t.get('threshold_mm'):
        ax2.axhline(t['threshold_mm'], color='#dc2626', ls='--', lw=1.2, label=f"Threshold {t['threshold_mm']} mm")
    ax.set_ylabel('Rainfall (mm)'); ax2.set_ylabel('API (mm)')
    ax.set_title('Rainfall and Antecedent Precipitation Index', fontsize=10)
    ax.tick_params(labelsize=7); ax2.tick_params(labelsize=7)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, fontsize=7, loc='upper left')
    return _fig_bytes(fig)


# ------------------------------- PDF builder -------------------------------- #
def _img(buf, max_w_cm, max_h_cm):
    """ReportLab Image na hindi napipiga (tinutuloy ang aspect ratio ng figure)."""
    w, h = PILImage.open(buf).size
    buf.seek(0)
    scale = min(max_w_cm * cm / w, max_h_cm * cm / h)
    return Image(buf, width=w * scale, height=h * scale)


def _dt(dt, fmt='%Y-%m-%d %H:%M'):
    """Local (Asia/Manila) time sa PDF, hindi UTC."""
    if dt is None:
        return '-'
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.strftime(fmt)


def _fmt(v, nd=3, suffix=''):
    return '-' if v is None else f'{v:.{nd}f}{suffix}'


def _table(data, col_widths=None, header=True):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]
    if header:
        style += [('BACKGROUND', (0, 0), (-1, 0), BLUE), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                  ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')]
    t.setStyle(TableStyle(style))
    return t


def generate_report_pdf(event, predictions, primary=None, outlets=()):
    """Returns PDF bytes. predictions: FloodPrediction list ng event (kahit ilan)."""
    preds = latest_per_event_and_type(list(predictions))
    if not preds:
        raise ValueError('Walang predictions para sa event na ito.')
    if primary is None:
        scored = [p for p in preds if p.iou_score is not None]
        primary = max(scored, key=lambda p: p.iou_score) if scored else preds[0]

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Title'], textColor=BLUE, fontSize=19, spaceAfter=4)
    h2 = ParagraphStyle('h2', parent=styles['Heading2'], textColor=BLUE, fontSize=12.5, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle('body', parent=styles['BodyText'], fontSize=9, leading=12.5)
    small = ParagraphStyle('small', parent=body, fontSize=7.5, textColor=colors.HexColor('#64748b'))

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title=f'Project Alluvion Report - {event.event_name}', author='Project Alluvion')
    S = []
    S.append(Paragraph('Project Alluvion', h1))
    S.append(Paragraph('AI-Powered Flood Hazard Mapping using Sentinel-1 SAR Imagery and Local Weather Station Data', body))
    S.append(Spacer(1, 6))
    S.append(_table([
        ['Flood event', event.event_name],
        ['Study area', 'Barangay Tumana, Marikina City'],
        ['Date occurred', str(event.date_occurred)],
        ['Primary imagery type', f'{imagery_label(primary.imagery_type)} (highest IoU)' if primary.iou_score is not None
         else imagery_label(primary.imagery_type)],
        ['Report generated', _dt(timezone.now(), '%B %d, %Y %H:%M')],
    ], [4.2 * cm, 12.8 * cm], header=False))
    if 'DUMMY' in (event.event_name or '').upper():
        S.append(Spacer(1, 4))
        S.append(Paragraph('<b>NOTE:</b> This event uses DUMMY / synthetic data for system testing only.', body))

    # 1. Summary outputs
    S.append(Paragraph('1. Summary of Outputs', h2))
    S.append(_table([
        ['Output', 'Value'],
        ['Total classified flood pixels', f'{primary.predicted_magnitude_pixels:,}'],
        ['Total land (valid) pixels', f'{primary.total_land_pixels:,}' if primary.total_land_pixels else '-'],
        ['Flood pixels relative to total land pixels', f'{primary.flood_percentage:.2f}%'],
        ['Predicted flood time', _dt(primary.predicted_time)],
    ], [8.5 * cm, 8.5 * cm]))

    # 2/3 Maps
    S.append(Paragraph('2. Flood Extent Map', h2))
    S.append(_img(_map_figure(event, primary, outlets, 'extent'), 14, 12))
    S.append(PageBreak())
    S.append(Paragraph('3. Flood Hazard Map', h2))
    S.append(_img(_map_figure(event, primary, outlets, 'hazard'), 14, 12))
    hz = (primary.explanation or {}).get('hazard') or {}
    S.append(Paragraph(
        f"Hazard distribution (pixels): Low {hz.get('low_px', 0):,} | Moderate {hz.get('moderate_px', 0):,} | "
        f"High {hz.get('high_px', 0):,}.", body))

    # 4. Evaluation
    S.append(Paragraph('4. Evaluation against Reference Data', h2))
    S.append(Paragraph('<b>4.1 Flood occurrence time</b>', body))
    S.append(_table([
        ['Predicted', 'Actual', 'Absolute error (hours)'],
        [_dt(primary.predicted_time),
         _dt(event.actual_flood_time),
         _fmt(primary.time_error_hours, 2)],
    ], [6 * cm, 6 * cm, 5 * cm]))
    S.append(Spacer(1, 4))
    S.append(Paragraph('<b>4.2 Flood magnitude</b>', body))
    act = event.actual_magnitude_pixels
    S.append(_table([
        ['Predicted pixels', 'Actual pixels', 'Absolute error (pixels)'],
        [f'{primary.predicted_magnitude_pixels:,}', f'{act:,}' if act is not None else '-',
         f'{abs(primary.predicted_magnitude_pixels - act):,}' if act is not None else '-'],
    ], [6 * cm, 6 * cm, 5 * cm]))
    S.append(Spacer(1, 4))
    S.append(Paragraph('<b>4.3 Flood-affected locations</b>', body))
    S.append(_table([
        ['IoU', 'Precision', 'Recall', 'F1-score'],
        [_fmt(primary.iou_score), _fmt(primary.precision), _fmt(primary.recall), _fmt(primary.f1_score)],
    ], [4.25 * cm] * 4))

    # 5. Imagery comparison
    S.append(Paragraph('5. Comparison of Sentinel-1 SAR Imagery Types', h2))
    ev = evaluate_predictions(preds)
    rows = [['Imagery type', 'Flood px', '% land', 'IoU', 'Precision', 'Recall', 'F1']]
    for p in sorted(preds, key=lambda x: (x.iou_score is None, -(x.iou_score or 0))):
        rows.append([imagery_label(p.imagery_type), f'{p.predicted_magnitude_pixels:,}', f'{p.flood_percentage:.2f}%',
                     _fmt(p.iou_score), _fmt(p.precision), _fmt(p.recall), _fmt(p.f1_score)])
    S.append(_table(rows, [3.4 * cm, 2.6 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm]))
    S.append(Spacer(1, 3))
    if ev['best']:
        S.append(Paragraph(f"For this event, <b>{ev['best']['label']}</b> produced the highest IoU "
                           f"({ev['best']['iou']:.3f}).", body))

    # 6. XAI
    S.append(PageBreak())
    S.append(Paragraph('6. Explainable AI (XAI) Analysis', h2))
    hist = _histogram_figure(primary)
    if hist:
        S.append(_img(hist, 15, 6.8))
    rain = _rainfall_figure(primary)
    if rain:
        S.append(_img(rain, 15, 6.8))
    for line in (primary.explanation or {}).get('summary', []):
        S.append(Paragraph(f'&bull; {line}', body))

    S.append(Spacer(1, 10))
    S.append(Paragraph(
        'Limitations: Sentinel-1 has medium spatial resolution (~20 m) and a 6-12 day revisit time; urban '
        'double-bounce can hide flooding; time prediction is based on daily rainfall and is therefore coarse. '
        'Results are limited to Barangay Tumana, Marikina City and the datasets used.', small))
    doc.build(S)
    return out.getvalue()
