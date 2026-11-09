"""
python manage.py seed_dummy_data            -> seed dummy outlets, weather, flood events, SAR images, legends
python manage.py seed_dummy_data --predict  -> also run prediction pipeline
python manage.py seed_dummy_data --reset    -> delete all DUMMY records first
ALL DATA IS SYNTHETIC - for demo/testing only.
"""
from datetime import date, datetime, timedelta

import numpy as np
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from flood.models import DrainageOutlet, FloodEvent, FloodPrediction, MapLegend
from flood.services import ai_model, dummy_data, pipeline
from satellite.models import SatelliteImage
from weather.models import WeatherRecord

STATION = 'PAGASA Marikina ARG (DUMMY)'
EVENTS = [
    ('Habagat Flood Aug 2018 (DUMMY)', date(2018, 8, 11), 0.50, 1),
    ('Typhoon Egay Jul 2023 (DUMMY)', date(2023, 7, 27), 0.40, 1),
    ('Typhoon Carina Jul 2024 (DUMMY)', date(2024, 7, 24), 0.80, 0),
    ('Typhoon Kristine Oct 2024 (DUMMY)', date(2024, 10, 24), 0.90, 1),
    ('Typhoon Ulysses Nov 2020 (DUMMY)', date(2020, 11, 12), 1.00, 0),
]
TRUE_THRESHOLD = 150.0
DECAY = 0.85

LEGENDS = [
    ('Low hazard zone', 'low', '#fde047', 'Minor flooding expected. Water may reach ankle level.', 1),
    ('Moderate hazard zone', 'moderate', '#fb923c', 'Significant flooding expected. Water may reach knee level.', 2),
    ('High hazard zone', 'high', '#dc2626', 'Severe flooding expected. Evacuation recommended.', 3),
]


def _aware(dt):
    return timezone.make_aware(dt) if getattr(settings, 'USE_TZ', False) else dt


def _imagery_choice_map():
    mapping = {}
    field = SatelliteImage._meta.get_field('imagery_type')
    for value, label in (field.choices or []):
        code = ai_model.normalize_imagery_type(label) or ai_model.normalize_imagery_type(value)
        if code:
            mapping[code] = value
    for code in ai_model.IMAGERY_CODES:
        mapping.setdefault(code, code)
    return mapping


class Command(BaseCommand):
    help = 'Seed DUMMY data (drainage outlets, rainfall, flood events, Sentinel-1 style GeoTIFFs, map legends).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete DUMMY records first')
        parser.add_argument('--predict', action='store_true', help='Run prediction after seeding')

    def handle(self, *args, **opts):
        if opts['reset']:
            self._reset()

        # Legends
        for name, cat, color, desc, order in LEGENDS:
            MapLegend.objects.update_or_create(
                name=name,
                defaults={'category': cat, 'color': color, 'description': desc, 'order': order, 'is_active': True},
            )
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(LEGENDS)} map legend categories.'))

        choice_map = _imagery_choice_map()
        self._seed_outlets()

        created_events = []
        for idx, (name, d, severity, offset) in enumerate(EVENTS):
            rng = np.random.default_rng(1000 + idx)
            actual_time = self._seed_rainfall(d, rng)
            truth = dummy_data.make_truth(severity, seed=2000 + idx)
            truth_geojson = ai_model.raster_to_geojson(truth.astype('uint8'), dummy_data.TRANSFORM, None,
                                                       class_labels={1: 'Flooded (reference)'})
            event, _ = FloodEvent.objects.update_or_create(
                event_name=name,
                defaults={
                    'date_occurred': d,
                    'description': 'DUMMY DATA - synthetic rainfall, SAR images and reference flood extent.',
                    'actual_flood_time': actual_time,
                    'actual_magnitude_pixels': int(truth.sum()),
                    'actual_extent_geojson': truth_geojson,
                },
            )
            created_events.append(event)

            for code in ai_model.IMAGERY_CODES:
                value = choice_map[code]
                acq = d + timedelta(days=offset)
                if SatelliteImage.objects.filter(imagery_type=value, acquisition_date=acq,
                                                 file__contains='dummy_').exists():
                    continue
                arr, nodata, _ = dummy_data.make_sar(truth, code, seed=3000 + idx * 10 + ai_model.IMAGERY_CODES.index(code))
                raw = dummy_data.geotiff_bytes(arr, nodata)
                img = SatelliteImage(imagery_type=value, acquisition_date=acq, is_processed=False)
                img.file.save(f'dummy_{d.isoformat()}_{code.lower()}.tif', ContentFile(raw), save=True)

            self.stdout.write(f'  - {name}: {int(truth.sum())} reference flood px')

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {DrainageOutlet.objects.filter(name__contains="DUMMY").count()} outlets, '
            f'{WeatherRecord.objects.filter(station_name=STATION).count()} rainfall rows, '
            f'{len(created_events)} events, '
            f'{SatelliteImage.objects.filter(file__contains="dummy_").count()} images.'))

        if opts['predict']:
            for ev in created_events:
                preds, msgs = pipeline.run_all_for_event(ev)
                self.stdout.write(f'  predicted {ev.event_name}: {len(preds)} runs')
                for m in msgs:
                    self.stdout.write(self.style.WARNING(f'    {m}'))

    def _reset(self):
        FloodPrediction.objects.filter(flood_event__event_name__contains='(DUMMY)').delete()
        FloodEvent.objects.filter(event_name__contains='(DUMMY)').delete()
        DrainageOutlet.objects.filter(name__contains='(DUMMY)').delete()
        WeatherRecord.objects.filter(station_name=STATION).delete()
        MapLegend.objects.filter(name__contains='DUMMY').delete()
        for img in SatelliteImage.objects.filter(file__contains='dummy_'):
            try:
                img.file.delete(save=False)
            except Exception:
                pass
            img.delete()
        self.stdout.write(self.style.WARNING('Dummy records deleted.'))

    def _seed_outlets(self):
        for name, lat, lon, elev in dummy_data.DUMMY_OUTLETS:
            DrainageOutlet.objects.update_or_create(
                name=name, defaults={'latitude': lat, 'longitude': lon, 'elevation': elev})

    def _seed_rainfall(self, event_date, rng):
        start = event_date - timedelta(days=14)
        rain = {}
        api = 0.0
        for i in range(11):
            d = start + timedelta(days=i)
            rain[d] = float(rng.gamma(1.2, 3.5)) if rng.random() < 0.7 else 0.0
            api = DECAY * api + rain[d]
        need = float(rng.uniform(55, 100))
        hour = float(rng.uniform(8, 20))
        d_minus1 = event_date - timedelta(days=1)
        for k, share in ((3, 0.18), (2, 0.30)):
            d = event_date - timedelta(days=k)
            rain[d] = float(rng.uniform(20, 55)) * (0.8 + share)
            api = DECAY * api + rain[d]
        api_prev_target = (TRUE_THRESHOLD - need) / DECAY
        rain[d_minus1] = max(api_prev_target - DECAY * api, 15.0)
        api = DECAY * api + rain[d_minus1]
        need_actual = max(TRUE_THRESHOLD - DECAY * api, 20.0)
        rain[event_date] = round(need_actual * 24 / hour, 1)
        rain[event_date + timedelta(days=1)] = float(rng.uniform(25, 85))

        for d, r in rain.items():
            WeatherRecord.objects.update_or_create(
                station_name=STATION, date_recorded=d,
                defaults={
                    'rainfall_mm': round(r, 1),
                    'temperature_c': round(float(rng.normal(26.5 if r > 40 else 29.5, 0.8)), 1),
                    'humidity_percent': round(float(np.clip(rng.normal(92 if r > 40 else 78, 4), 55, 100)), 1),
                })

        observed_hour = float(np.clip(hour + rng.normal(0, 2.0), 1, 23.5))
        naive = datetime.combine(event_date, datetime.min.time()) + timedelta(hours=observed_hour)
        return _aware(naive)