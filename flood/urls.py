# flood/urls.py
from django.urls import path

from . import api, views, views_manage, views_reports

urlpatterns = [
    # API
    path('api/run-prediction/', api.run_real_prediction_api, name='api_run_prediction'),

    # Main views
    path('', views.dashboard_view, name='dashboard'),
    path('map/', views.map_view, name='map'),
    path('notifications/', views.notifications_view, name='notifications'),

    # Evaluation + prediction detail (XAI)
    path('evaluation/', views_reports.evaluation_view, name='evaluation'),
    path('evaluation/export.csv', views_reports.evaluation_csv, name='evaluation_csv'),
    path('predictions/<int:pk>/', views_reports.prediction_detail_view, name='prediction_detail'),
    path('predictions/<int:pk>/delete/', views_manage.prediction_delete_view, name='prediction_delete'),

    # Digital PDF reports
    path('reports/event/<int:pk>/pdf/', views_reports.event_report_pdf, name='event_report'),
    path('reports/prediction/<int:pk>/pdf/', views_reports.prediction_report_pdf, name='prediction_report'),

    # Flood events (ground truth)
    path('events/', views_manage.events_view, name='events'),
    path('events/<int:pk>/edit/', views_manage.event_edit_view, name='event_edit'),
    path('events/<int:pk>/delete/', views_manage.event_delete_view, name='event_delete'),

    # Drainage outlets (paginated + click-on-map) -> views.outlets_view
    path('outlets/', views.outlets_view, name='outlets'),
    path('outlets/template.csv', views_manage.outlets_template_csv, name='outlets_template_csv'),
    path('outlets/<int:pk>/delete/', views_manage.outlet_delete_view, name='outlet_delete'),
]
