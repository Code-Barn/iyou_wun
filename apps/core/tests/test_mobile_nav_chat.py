from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class MobileNavChatAndNotificationCoordinationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="did:key:z6Mkmobilenavtestuser")

    def test_mobile_bottom_dock_chat_button_wiring(self):
        template = Template(
            '{% load static %}{% include "includes/_mobile_bottom_dock.html" %}'
        )
        context = Context({"user": self.user})
        rendered = template.render(context)

        # 1. Has explicit id mobile-nav-chat-btn
        self.assertIn('id="mobile-nav-chat-btn"', rendered)

        # 2. Points to https://chat.iyou.me fallback
        self.assertIn('href="https://chat.iyou.me"', rendered)

        # 3. Intercepts left-clicks and calls window.IyouChatDock.toggle()
        self.assertIn("!event.metaKey && !event.ctrlKey && event.button === 0", rendered)
        self.assertIn("window.IyouChatDock.toggle", rendered)
        self.assertIn("event.preventDefault()", rendered)

        # 4. Contains unread numeric pill
        self.assertIn('id="mobile-chat-unread-pill"', rendered)

    def test_base_template_dock_embed_offset_and_coordination(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # 1. Dock embed has data-mobile-bottom-offset="64px"
        self.assertIn('data-mobile-bottom-offset="64px"', content)

        # 2. Listens for iyou:chat:state and closes notification drawer & styles mobile chat button
        self.assertIn("iyou:chat:state", content)
        self.assertIn("closeNotificationDrawer", content)
        self.assertIn("mobile-nav-chat-btn", content)

        # 3. Listens for iyou:chat:unread_update and updates mobile-chat-unread-pill
        self.assertIn("iyou:chat:unread_update", content)
        self.assertIn("mobile-chat-unread-pill", content)

    def test_notification_manager_closes_chat_dock_on_open(self):
        from django.conf import settings
        js_file = settings.BASE_DIR / "static" / "js" / "notification_manager.js"
        content = js_file.read_text()

        # openDrawer must close window.IyouChatDock if present
        self.assertIn("NotificationManager.prototype.openDrawer", content)
        self.assertIn("window.IyouChatDock.close", content)
