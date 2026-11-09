# flood/admin.py
from django.contrib import admin
from .models import FloodEvent, FloodPrediction, DrainageOutlet, MapLegend


@admin.register(MapLegend)
class MapLegendAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'color', 'order', 'is_active')
    list_editable = ('order', 'is_active', 'color')
    list_filter = ('category', 'is_active')


admin.site.register(FloodEvent)
admin.site.register(FloodPrediction)
admin.site.register(DrainageOutlet)