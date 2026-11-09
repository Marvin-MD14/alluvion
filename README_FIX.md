# Fix: "Access blocked" sa OSM tiles ng Drainage Outlets

Sanhi: Django default = Referrer-Policy: same-origin -> walang Referer papuntang OpenStreetMap -> 403.
(Gumana ang map.html dahil may referrerPolicy ang tileLayer niya.)

## I-copy (i-overwrite)
templates/flood/outlets.html  - may referrerPolicy, lahat ng outlets ay lumalabas sa mapa (hindi lang current page), marker sa pinili mong lokasyon
flood/views.py                - tinanggal ang sirang SentinelImage/placeholder views; outlets_view may validation; events/evaluation ay galing sa views_manage/views_reports
flood/urls.py                 - 'outlets' -> views.outlets_view (paginated)

## OPTIONAL pero inirerekomenda: config/settings.py (aayos sa LAHAT ng maps, kasama ang prediction_detail)
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

## Kailangan
- models.py ay may MapLegend (nasa project mo na); walang bagong migration.
- Hard refresh (Ctrl+F5) pagkatapos.
