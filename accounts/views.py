from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib import messages

def register_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        
        # Validation
        if not username or not password:
            messages.error(request, 'Username and password are required.')
            return redirect('login')
            
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists. Please choose another.')
            return redirect('login')
            
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email is already registered.')
            return redirect('login')
            
        # Gumawa ng bagong user
        user = User.objects.create_user(username=username, email=email, password=password)
        user.save()
        
        # ✅ AUTO-LOGIN PAGKATAPOS MAG-REGISTER
        login(request, user)
        
        messages.success(request, 'Account created successfully! Welcome to Project Alluvion.')
        return redirect('dashboard')  # Direkta sa dashboard
        
    # Kung GET request, i-redirect sa login page
    return redirect('login')