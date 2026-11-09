from django.urls import path

from . import views

urlpatterns = [
    path('', views.weather_records_view, name='weather_records'),
    path('template.csv', views.weather_template_csv, name='weather_template_csv'),
]
