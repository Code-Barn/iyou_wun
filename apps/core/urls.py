from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard', views.dashboard, name='dashboard'),
    path('feed', views.FeedView.as_view(), name='feed'),
    path('gallery', views.GalleryView.as_view(), name='gallery'),
    path('profile/<str:npub>/', views.ProfileView.as_view(), name='profile'),
    path('chat', views.ChatView.as_view(), name='chat'),
    path('api/relays', views.api_relays, name='api_relays'),
    path('api/feed', views.api_feed, name='api_feed'),
]
