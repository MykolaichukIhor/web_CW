from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from django.views.generic.base import RedirectView
from django.urls import reverse_lazy

from . import views

# Дозволяємо GET тільки для зворотної сумісності, але виконуємо вихід
class CustomLogoutView(LogoutView):
    http_method_names = ['get', 'post']
    
    def get(self, request, *args, **kwargs):
        # Виконуємо вихід навіть при GET-запиті
        return self.post(request, *args, **kwargs)

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='gallery', permanent=False)),
    path('signup/', views.signup, name='signup'),
    path('login/', LoginView.as_view(template_name='photos/login.html'), name='photos_login'),
    path('logout/', CustomLogoutView.as_view(next_page=reverse_lazy('photos_login')), name='logout'),
    path('gallery/', views.gallery, name='gallery'),
    path('gallery-mobile/', views.gallery, name='gallery_mobile'),
    
    path('photo/<str:pk>/', views.viewPhoto, name='photo'),
    path('upload/', views.uploadPhoto, name='upload'),
    path('photo/<str:pk>/edit/', views.editPhoto, name='edit'),
    path('photo/<int:pk>/edit-mobile/', views.editPhoto, name='edit_mobile'),
    path('photo/<str:pk>/delete/', views.deletePhoto, name='delete'),
    path('photo/<str:pk>/delete-mobile/', views.deletePhoto, name='delete_mobile'),
    path('edit/<str:pk>/preview/', views.previewPhoto, name='preview_photo'),
    
]