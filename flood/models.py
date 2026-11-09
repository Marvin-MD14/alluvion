# flood/models.py
from django.db import models
from satellite.models import SatelliteImage


class DrainageOutlet(models.Model):
    name = models.CharField(max_length=100)
    latitude = models.FloatField()
    longitude = models.FloatField()
    elevation = models.FloatField(help_text="Elevation in meters")

    def __str__(self):
        return self.name


class FloodEvent(models.Model):
    event_name = models.CharField(max_length=100)
    date_occurred = models.DateField()
    description = models.TextField(blank=True, null=True)

    # GROUND TRUTH (for Evaluation: MAE, RMSE, R2, IoU, Precision, Recall, F1)
    actual_flood_time = models.DateTimeField(null=True, blank=True, help_text="Actual flood time")
    actual_magnitude_pixels = models.IntegerField(null=True, blank=True, help_text="Actual flood pixels")
    actual_extent_geojson = models.JSONField(null=True, blank=True, help_text="Reference map (GeoJSON)")

    def __str__(self):
        return f"{self.event_name} ({self.date_occurred})"


class FloodPrediction(models.Model):
    flood_event = models.ForeignKey(FloodEvent, on_delete=models.CASCADE, related_name='predictions')
    satellite_image = models.ForeignKey(SatelliteImage, on_delete=models.SET_NULL, null=True, blank=True)

    imagery_type = models.CharField(max_length=20, blank=True, null=True)
    predicted_time = models.DateTimeField(help_text="Predicted flood time")
    predicted_magnitude_pixels = models.IntegerField(help_text="Number of flood pixels")
    flood_percentage = models.FloatField(help_text="Percentage of flood pixels")
    total_land_pixels = models.IntegerField(null=True, blank=True)

    precision = models.FloatField(null=True, blank=True)
    recall = models.FloatField(null=True, blank=True)
    f1_score = models.FloatField(null=True, blank=True)
    iou_score = models.FloatField(null=True, blank=True)
    time_error_hours = models.FloatField(null=True, blank=True, help_text="Difference in hours (MAE)")

    flood_extent_geojson = models.JSONField(null=True, blank=True, help_text="Flood extent GeoJSON")
    hazard_geojson = models.JSONField(null=True, blank=True, help_text="Hazard map GeoJSON (Low/Moderate/High)")

    explanation = models.JSONField(null=True, blank=True, help_text="XAI explanation")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Prediction for {self.flood_event.event_name} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


# ✅ NEW: Admin-managed legend categories for the Flood Map
class MapLegend(models.Model):
    HAZARD_CHOICES = [
        ('low', 'Low Hazard'),
        ('moderate', 'Moderate Hazard'),
        ('high', 'High Hazard'),
    ]

    name = models.CharField(max_length=80, help_text="Label shown in the map legend, e.g. 'Low hazard zone'")
    category = models.CharField(max_length=20, choices=HAZARD_CHOICES, default='low')
    color = models.CharField(max_length=7, default='#fde047',
                             help_text="Hex color (#RRGGBB). e.g. #fde047 = yellow, #fb923c = orange, #dc2626 = red")
    description = models.TextField(blank=True, help_text="Short explanation of what this zone means")
    geojson = models.JSONField(
        null=True, blank=True,
        help_text="Optional polygon GeoJSON (lon/lat). If empty, the category is drawn from the prediction hazard map."
    )
    order = models.PositiveIntegerField(default=0, help_text="Sort order in legend (lower = first)")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Map Legend Category"
        verbose_name_plural = "Map Legend Categories"

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"