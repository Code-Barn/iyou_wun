"""Canonical 13-Test Suite for GeographicRoutingMiddleware per SPEC-008."""

from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase

from apps.core.middleware import GeographicRoutingMiddleware


class GeographicRoutingMiddlewareTestCase(TestCase):
    """SPEC-008 Canonical 13-scenario test suite for geographic subdomain routing."""

    def setUp(self):
        self.rf = RequestFactory()
        self.middleware = GeographicRoutingMiddleware(get_response=lambda req: HttpResponse("OK"))

    def test_bare_domain_returns_global_scope(self):
        request = self.rf.get("/healthz", HTTP_HOST="wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(request.geographic_scope)
        self.assertEqual(request.scope_tokens, ())
        self.assertIsNone(request.jurisdiction_level)

    def test_single_country_code(self):
        request = self.rf.get("/healthz", HTTP_HOST="us.wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.geographic_scope, "us")
        self.assertEqual(request.scope_tokens, ("us",))
        self.assertEqual(request.jurisdiction_level, "country")

    def test_state_country_hierarchy(self):
        request = self.rf.get("/healthz", HTTP_HOST="il.us.wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.geographic_scope, "il.us")
        self.assertEqual(request.scope_tokens, ("il", "us"))
        self.assertEqual(request.jurisdiction_level, "state")

    def test_county_state_country_hierarchy(self):
        request = self.rf.get("/healthz", HTTP_HOST="dkc.il.us.wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.geographic_scope, "dkc.il.us")
        self.assertEqual(request.scope_tokens, ("dkc", "il", "us"))
        self.assertEqual(request.jurisdiction_level, "county")

    def test_city_tier_hierarchy(self):
        request = self.rf.get("/healthz", HTTP_HOST="chi.cook.il.us.wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.geographic_scope, "chi.cook.il.us")
        self.assertEqual(request.scope_tokens, ("chi", "cook", "il", "us"))
        self.assertEqual(request.jurisdiction_level, "city")

    def test_ward_tier_hierarchy(self):
        request = self.rf.get("/healthz", HTTP_HOST="ward5.chi.cook.il.us.wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.geographic_scope, "ward5.chi.cook.il.us")
        self.assertEqual(request.scope_tokens, ("ward5", "chi", "cook", "il", "us"))
        self.assertEqual(request.jurisdiction_level, "ward")

    def test_system_keyword_bypasses_geographic(self):
        for sys_sub in ["api", "admin", "static", "media", "ws", "relay"]:
            request = self.rf.get("/healthz", HTTP_HOST=f"{sys_sub}.wun.iyou.me")
            response = self.middleware(request)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(request.geographic_scope)
            self.assertIsNone(request.jurisdiction_level)

    def test_api_keyword_bypasses_geographic(self):
        request = self.rf.get("/healthz", HTTP_HOST="api.wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(request.geographic_scope)
        self.assertIsNone(request.jurisdiction_level)

    def test_www_stripped_correctly(self):
        request = self.rf.get("/healthz", HTTP_HOST="www.wun.iyou.me")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(request.geographic_scope)
        self.assertIsNone(request.jurisdiction_level)

    def test_invalid_country_raises_404(self):
        request = self.rf.get("/healthz", HTTP_HOST="il.xx.wun.iyou.me")
        with self.assertRaises(Http404):
            self.middleware(request)

    def test_invalid_state_raises_404(self):
        request = self.rf.get("/healthz", HTTP_HOST="dkc.zz.us.wun.iyou.me")
        with self.assertRaises(Http404):
            self.middleware(request)

    def test_localhost_bare_returns_global(self):
        request = self.rf.get("/healthz", HTTP_HOST="localhost:8000")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(request.geographic_scope)
        self.assertIsNone(request.jurisdiction_level)

    def test_localhost_with_geo(self):
        request = self.rf.get("/healthz", HTTP_HOST="us.localhost:8000")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.geographic_scope, "us")
        self.assertEqual(request.scope_tokens, ("us",))
        self.assertEqual(request.jurisdiction_level, "country")
