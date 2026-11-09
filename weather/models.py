from django.db import models

class WeatherRecord(models.Model):
    station_name = models.CharField(max_length=100, default="PAGASA Station")
    date_recorded = models.DateField()
    rainfall_mm = models.FloatField(help_text="Rainfall in millimeters (mm)")
    temperature_c = models.FloatField(null=True, blank=True, help_text="Temperature in Celsius")
    humidity_percent = models.FloatField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.station_name} - {self.date_recorded} ({self.rainfall_mm}mm)"

    class Meta:
        verbose_name = "Weather Record"
        verbose_name_plural = "Weather Records"