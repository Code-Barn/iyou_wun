"""Canonical 13-Test Suite discovery entrypoint and geographic feed query tests in apps.core.tests."""

from unittest.mock import patch
from django.test import RequestFactory, TestCase

from apps.core.context_processors import geographic_context
from apps.core.views import api_feed, fetch_unified_feed
from tests.test_geographic_middleware import GeographicRoutingMiddlewareTestCase

__all__ = ["GeographicRoutingMiddlewareTestCase", "GeographicFeedQueryTestCase"]


class GeographicFeedQueryTestCase(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_geographic_context_processor(self):
        request = self.rf.get("/")
        request.geographic_scope = "dkc.il.us"
        request.jurisdiction_level = "county"
        ctx = geographic_context(request)
        self.assertEqual(ctx["GEOGRAPHIC_SCOPE"], "dkc.il.us")
        self.assertEqual(ctx["JURISDICTION_LEVEL"], "county")
        self.assertEqual(ctx["POLY_BASE_DOMAIN"], "poly.iyou.me")

    def test_api_feed_geo_filter_and_kind_1112(self):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.sessions.middleware import SessionMiddleware
        request = self.rf.get("/api/feed/")
        request.user = AnonymousUser()
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.geographic_scope = "dkc.il.us"
        request.scope_tokens = ("dkc", "il", "us")
        request.jurisdiction_level = "county"

        captured_filter = {}

        def fake_relay_req(filt, **kwargs):
            nonlocal captured_filter
            captured_filter = filt
            return {}

        with patch("apps.core.views.relay_req", side_effect=fake_relay_req):
            response = api_feed(request)
            self.assertEqual(response.status_code, 200)

        self.assertIn(1112, captured_filter.get("kinds", []))
        self.assertEqual(captured_filter.get("kinds"), [1, 1063, 1111, 1112, 30023])
        self.assertEqual(captured_filter.get("#geo"), ["dkc.il.us", "il.us", "us"])

    def test_fetch_unified_feed_geo_filter_and_kind_1112(self):
        request = self.rf.get("/")
        request.geographic_scope = "dkc.il.us"
        request.scope_tokens = ("dkc", "il", "us")
        request.jurisdiction_level = "county"

        captured_filter = {}

        def fake_relay_req(filt, **kwargs):
            nonlocal captured_filter
            captured_filter = filt
            return {}

        with patch("apps.core.views.relay_req", side_effect=fake_relay_req):
            fetch_unified_feed(request=request)

        self.assertIn(1112, captured_filter.get("kinds", []))
        self.assertEqual(captured_filter.get("kinds"), [1, 1063, 1111, 1112, 30023])
        self.assertEqual(captured_filter.get("#geo"), ["dkc.il.us", "il.us", "us"])
