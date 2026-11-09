from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator  # ✅ Idinagdag para sa pagination
from .forms import SatelliteImageForm
from .models import SatelliteImage

@login_required
def upload_image_view(request):
    if request.method == 'POST':
        form = SatelliteImageForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Sentinel-1 image uploaded successfully!")
            return redirect('upload_image')
        else:
            messages.error(request, "There was an error uploading the image. Please check the form.")
    else:
        form = SatelliteImageForm()
    
    # ✅ PAGINATION LOGIC
    images_list = SatelliteImage.objects.all().order_by('-uploaded_at')
    paginator = Paginator(images_list, 10)  # 10 rows per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # ✅ Ipinasa ang 'images' bilang page_obj para gumana ang start_index/end_index sa template
    return render(request, 'satellite/upload.html', {'form': form, 'images': page_obj})