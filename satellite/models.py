from django.db import models


class SatelliteImage(models.Model):
    """Sentinel-1 SAR GeoTIFF (5 imagery types na ikukumpara sa thesis)."""
    IMAGERY_CHOICES = [
        ('VH_LINEAR', 'VH Linear'),
        ('VH_GAMMA', 'VH Gamma'),
        ('VV_LINEAR', 'VV Linear'),
        ('VV_GAMMA', 'VV Gamma'),
        ('SAR_URBAN', 'SAR Urban'),
    ]

    imagery_type = models.CharField(max_length=20, choices=IMAGERY_CHOICES)
    acquisition_date = models.DateField()
    file = models.FileField(upload_to='satellite_images/')
    is_processed = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Satellite Image'
        verbose_name_plural = 'Satellite Images'

    def __str__(self):
        return f"{self.get_imagery_type_display()} - {self.acquisition_date}"
