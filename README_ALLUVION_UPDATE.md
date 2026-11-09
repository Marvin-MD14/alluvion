# Project Alluvion – Update Pack

## 1. Kopyahin ang mga files (i-overwrite kung meron na)
| File sa zip | Saan ilalagay |
|---|---|
| flood/models.py | flood/models.py (**may bagong fields** → kailangan ng migration) |
| flood/api.py | flood/api.py |
| flood/urls.py | flood/urls.py |
| flood/views_reports.py | flood/views_reports.py (bago) |
| flood/services/*.py | flood/services/ (ai_model, time_model, evaluation, explain, pipeline, report, dummy_data) |
| flood/management/commands/seed_dummy_data.py | parehong path (kasama ang __init__.py ng `management/` at `commands/`) |
| satellite/models.py | satellite/models.py (nilagyan ng 5 imagery choices) |
| weather/views.py, weather/urls.py | weather/ (bago) |
| templates/base.html, templates/flood/dashboard.html | overwrite |
| templates/flood/evaluation.html, prediction_detail.html | templates/flood/ (bago) |
| templates/weather/records.html | templates/weather/ (bago) |

> Hindi ko ginalaw ang `flood/views.py`, `flood/admin.py`, `flood/services/metrics.py`, `weather/models.py`, `satellite/views.py`, `templates/flood/map.html`.

## 2. config/urls.py – idagdag
```python
path('weather/', include('weather.urls')),
```
(katabi ng `path('satellite/', include('satellite.urls'))`)

## 3. Install + migrate
```bash
pip install -r requirements_additions.txt
python manage.py makemigrations flood satellite
python manage.py migrate
```
Kung may error sa migration ng `flood` dahil sa lumang rows, i-delete muna ang lumang FloodPrediction rows sa admin.

## 4. Dummy data (para sa testing / demo lang)
```bash
python manage.py seed_dummy_data --predict
# ulitin nang malinis:
python manage.py seed_dummy_data --reset --predict
```
Lahat ng may "(DUMMY)" ay synthetic. Tinatanggal ng `--reset` ang mga iyon lang.

## 5. Mga bagong pages
- `/evaluation/` – MAE/RMSE/R², IoU/Precision/Recall/F1 per imagery type
- `/predictions/<id>/` – map (extent + hazard + reference + outlets), XAI, rainfall/API chart
- `/reports/event/<id>/pdf/` at `/reports/prediction/<id>/pdf/` – Digital PDF report
- `/weather/` – upload ng PAGASA rainfall CSV (template: `/weather/template.csv`, sample: `sample_weather_dummy.csv`)
