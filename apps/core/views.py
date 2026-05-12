from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
import json
import ssl
import threading
import time
from datetime import datetime
from websocket import WebSocketApp
import bech32


def home(request):
    print(f"DEBUG: Middleware check - User in request: {request.user}")
    print(f"DEBUG: Cookies received at index: {request.COOKIES.keys()}")
    print(f"DEBUG: Session user at index: {request.user}, Authenticated: {request.user.is_authenticated}")
    print(f"!!! ACCESSING HOME - USER: {request.user} - AUTH: {request.user.is_authenticated} !!!")
    if hasattr(request, 'session'):
        print(f"DEBUG: Session ID: {request.session.session_key}")
        print(f"DEBUG: Session data: {dict(request.session)}")
    else:
        print("DEBUG: No session object found!")
    if request.user.is_authenticated:
        return redirect('feed')
    return render(request, 'home.html')


@login_required
def dashboard(request):
    return render(request, 'dashboard.html')


class FeedView(LoginRequiredMixin, TemplateView):
    template_name = 'feed.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Debug print to confirm authentication
        print(f"DEBUG: Rendering feed for user {self.request.user}")

        # Fetch Kind 1 events from Nostr relay
        notes = fetch_nostr_notes()
        context['notes'] = notes

        return context

    def get(self, request, *args, **kwargs):
        # Add welcome message for first-time users
        if not request.session.get('has_seen_feed_welcome', False):
            from django.contrib import messages
            messages.success(request, "Welcome to the Omni-Social Feed. Your identity is verified and sovereign.")
            request.session['has_seen_feed_welcome'] = True

        return super().get(request, *args, **kwargs)


def fetch_nostr_notes(limit=20):
    """Fetch the last N Kind 1 (Short Text Note) events from a public relay."""
    relay_url = 'wss://nos.lol'
    notes = []
    done = threading.Event()

    def on_open(ws):
        req = json.dumps(['REQ', 'wun_feed', {'kinds': [1], 'limit': limit}])
        ws.send(req)

    def on_message(ws, raw):
        try:
            msg = json.loads(raw)
            if msg[0] == 'EVENT' and msg[1] == 'wun_feed':
                e = msg[2]
                pubkey = e.get('pubkey', '')
                npub = hex_to_npub(pubkey) if pubkey else ''
                notes.append({
                    'pubkey': pubkey,
                    'npub': npub,
                    'content': e.get('content', ''),
                    'created_at': datetime.fromtimestamp(e.get('created_at', 0)),
                })
            elif msg[0] == 'EOSE':
                done.set()
        except Exception:
            pass

    def on_error(ws, err):
        done.set()

    def on_close(ws, status, msg):
        done.set()

    ws = WebSocketApp(
        relay_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    try:
        t = threading.Thread(
            target=ws.run_forever,
            kwargs={'sslopt': {'cert_reqs': ssl.CERT_NONE}},
            daemon=True,
        )
        t.start()
        done.wait(timeout=10)
        ws.close()
    except Exception as e:
        print(f"Error fetching Nostr notes: {e}")

    return notes[:limit]


def hex_to_npub(hex_pubkey):
    """Convert hex pubkey to NIP-19 npub format."""
    try:
        # Convert hex to bytes
        data = bytes.fromhex(hex_pubkey)
        # Encode using bech32
        converted = bech32.bech32_encode('npub', bech32.convertbits(data, 8, 5))
        return converted
    except Exception:
        return hex_pubkey[:12] + '...'  # Fallback to truncated hex
