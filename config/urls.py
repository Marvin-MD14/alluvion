from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from accounts import views as accounts_views
from django.views.generic import RedirectView # ✅ IDINAGDAG ITO

urlpatterns = [
    # Admin Panel
    path('admin/', admin.site.urls),
    
    # Authentication
    path('accounts/login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='/accounts/login/'), name='logout'),
    path('accounts/register/', accounts_views.register_view, name='register'),
    
    # ✅ IDINAGDAG ITO PARA SA /accounts/profile/
    path('accounts/profile/', RedirectView.as_view(url='/', permanent=False), name='profile'),
    
    # App URLs
    path('', include('flood.urls')),
    path('satellite/', include('satellite.urls')),
    path('weather/', include('weather.urls')),
]

# Para lumabas ang uploaded files sa development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)