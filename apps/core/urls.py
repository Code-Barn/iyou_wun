# Copyright (C) 2026 David Byers dba Byers Brands
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

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
    path('api/vote', views.api_cast_vote, name='api_cast_vote'),
    path('api/credentials/issue/', views.IssueCredentialView.as_view(), name='api_issue_credential'),
    path('api/config/', views.node_config, name='node_config'),
]
