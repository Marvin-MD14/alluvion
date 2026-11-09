# Project Alluvion - Fix + Functional Update

## Ano ang error?
`flood/services/ai_model.py` ay na-overwrite ng laman ng `api.py` (kaya `from .services.ai_model import` sa line 11 -> `flood.services.services`).
Ang zip na ito ay may bagong, kumpletong `ai_model.py`.

## I-copy (i-overwrite) - walang bagong migration
flood/services/ai_model.py   (BAGO - ito ang nag-fix ng error)
flood/services/pipeline.py
flood/api.py
flood/forms.py               (bago)
flood/views.py               (may stray "}" sa dulo ng dati mong file = syntax error; naayos)
flood/views_reports.py
flood/views_manage.py        (bago)
flood/urls.py
templates/base.html
templates/flood/map.html, prediction_detail.html, evaluation.html
templates/flood/events.html, outlets.html   (bago)

## Run
pip install -r requirements_additions.txt
python manage.py runserver
(Optional demo data:  python manage.py seed_dummy_data --reset --predict)

## Bagong features
- /events/    : add/edit/delete flood events + actual time, actual pixels, reference GeoJSON upload, Run prediction, PDF
- /outlets/   : add/delete drainage outlets + CSV import + map
- /map/       : pumili ng prediction; hazard (Low/Moderate/High), flood extent, reference, outlets layers
- /predictions/<id>/ : tunay na XAI (threshold, histogram, separability, rainfall/API chart, contributions)
- /reports/event/<id>/pdf/ at /reports/prediction/<id>/pdf/ : Digital PDF report
- /evaluation/export.csv : evaluation table para sa thesis
- Prediction: lahat ng 5 imagery types, Sentinel-1 images na +/-7 araw ng event date, Otsu + hazard + API time model
