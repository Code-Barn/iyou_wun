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

from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard', views.dashboard, name='dashboard'),
    path('feed', views.FeedView.as_view(), name='feed'),
    path('notifications/', views.NotificationsView.as_view(), name='notifications'),
    path('gallery', views.GalleryView.as_view(), name='gallery'),
    path('profile/<str:npub>/', views.ProfileView.as_view(), name='profile'),
    path('chat', views.ChatView.as_view(), name='chat'),
    path('api/relays', views.api_relays, name='api_relays'),
    path('api/feed', views.api_feed, name='api_feed'),
    path('api/search/', views.api_search, name='api_search'),
    path('api/translate/', views.api_translate, name='api_translate'),
    path('api/chat/session/', views.api_chat_session, name='api_chat_session'),
    path('api/profile/save/', views.api_save_profile, name='api_save_profile'),
    path('api/vote', views.api_cast_vote, name='api_cast_vote'),

    path('api/media/upload/', views.MediaUploadProxyView.as_view(), name='media_upload_proxy'),
    path('api/credentials/issue/', views.IssueCredentialView.as_view(), name='api_issue_credential'),
    path('api/config/', views.node_config, name='node_config'),
    path('.well-known/nostr.json', views.nip05_well_known, name='nip05_well_known'),
]

urlpatterns += [
    re_path(
        r"^@(?P<handle>[a-z0-9_-]{3,32})(?:\[(?P<disc>\d+)\])?/?$",
        views.LinkDeckView.as_view(),
        name="link_deck",
    ),
    path("u/<str:did_key>/", views.LinkDeckView.as_view(), name="link_deck_did"),
    path("api/deck/handle", views.api_deck_handle, name="api_deck_handle"),
    path("api/deck/items", views.api_deck_items, name="api_deck_items"),
    path("api/deck/items/<int:pk>", views.api_deck_item_detail, name="api_deck_item_detail"),
    path("api/deck/reorder", views.api_deck_reorder, name="api_deck_reorder"),
    path("api/deck/verify/challenge", views.api_deck_verify_challenge, name="api_deck_verify_challenge"),
    path("api/deck/verify/confirm", views.api_deck_verify_confirm, name="api_deck_verify_confirm"),
]

