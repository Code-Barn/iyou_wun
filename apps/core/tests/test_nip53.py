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

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.core.nip53 import filter_active_live_rooms, parse_nip53_event

from .helpers import make_event, VALID_PUBKEY_HEX

SECOND_PUBKEY_HEX = "a1b2c3d4e5f60718293a4b5c6d7e8f9012a3b4c5d6e7f8091a2b3c4d5e6f70819"


def live_room_event(eid, d_tag="", title="", summary="", streaming="", status="live",
                    participants=0, image="", host=None, pubkey=None, created_at=None):
    tags = []
    if d_tag:
        tags.append(["d", d_tag])
    if title:
        tags.append(["title", title])
    if summary:
        tags.append(["summary", summary])
    if streaming:
        tags.append(["streaming", streaming])
    if status:
        tags.append(["status", status])
    if participants:
        tags.append(["current_participants", str(participants)])
    if image:
        tags.append(["image", image])
    if host:
        tags.append(["p", host, "", "host"])
    return make_event(
        eid,
        30311,
        pubkey=pubkey or VALID_PUBKEY_HEX,
        tags=tags,
        created_at=created_at or 1700000000,
    )


class ParseNip53EventTests(TestCase):
    def test_parse_valid_kind_30311_event(self):
        event = make_event(
            "ev_30311_1",
            30311,
            tags=[
                ["d", "town-hall-042"],
                ["title", "Sovereign Town Hall"],
                ["summary", "Weekly mesh governance call with the community."],
                ["streaming", "https://cdn.iyou.me/town-hall.m3u8"],
                ["status", "live"],
                ["current_participants", "42"],
                ["image", "https://cdn.iyou.me/town-hall.jpg"],
                ["relays", "wss://relay.iyou.me", "wss://relay2.iyou.me"],
                ["p", "deadbeefcafef00d", "", "host"],
            ],
            created_at=1700000300,
        )

        room = parse_nip53_event(event)

        self.assertIsNotNone(room)
        self.assertEqual(room["id"], "ev_30311_1")
        self.assertEqual(room["d_tag"], "town-hall-042")
        self.assertEqual(room["title"], "Sovereign Town Hall")
        self.assertEqual(room["summary"], "Weekly mesh governance call with the community.")
        self.assertEqual(room["streaming_url"], "https://cdn.iyou.me/town-hall.m3u8")
        self.assertEqual(room["status"], "live")
        self.assertEqual(room["current_participants"], 42)
        self.assertEqual(room["image_url"], "https://cdn.iyou.me/town-hall.jpg")
        # Host role from p-tag wins over the event pubkey
        self.assertEqual(room["host_pubkey"], "deadbeefcafef00d")
        self.assertEqual(room["relays"], ["wss://relay.iyou.me", "wss://relay2.iyou.me"])
        self.assertEqual(room["created_at"], 1700000300)

    def test_parse_ignores_non_30311_kinds_and_malformed_input(self):
        self.assertIsNone(parse_nip53_event(make_event("ev_kind1", 1)))
        self.assertIsNone(parse_nip53_event({"kind": 30312, "tags": [["title", "Nope"]]}))
        self.assertIsNone(parse_nip53_event("not a dict"))
        self.assertIsNone(parse_nip53_event(None))
        self.assertIsNone(parse_nip53_event([["title", "Nope"]]))
        self.assertIsNone(parse_nip53_event({}))

    def test_parse_title_fallbacks_summary_then_d_tag(self):
        # 40-char summary truncation, then d-tag, then generic placeholder
        room = parse_nip53_event(live_room_event("ev_a", d_tag="sh", summary="A really long summary that exceeds forty characters in length."))
        self.assertEqual(room["title"], "A really long summary that exceeds forty")

        # No title/summary -> d-tag, then generic placeholder
        room = parse_nip53_event(live_room_event("ev_b", d_tag="nightly-checkin"))
        self.assertEqual(room["title"], "nightly-checkin")
        room = parse_nip53_event(live_room_event("ev_c"))
        self.assertEqual(room["title"], "Untitled Space")

    def test_parse_host_falls_back_to_event_pubkey(self):
        event = make_event(
            "ev_30311_2",
            30311,
            pubkey=VALID_PUBKEY_HEX,
            tags=[["title", "No host tag"]],
        )
        room = parse_nip53_event(event)
        self.assertEqual(room["host_pubkey"], VALID_PUBKEY_HEX)

    def test_parse_bad_participant_count_resolves_to_zero(self):
        room = parse_nip53_event(live_room_event("ev_bad", participants="not-a-number"))
        self.assertEqual(room["current_participants"], 0)
        # Default status is 'planned' when the status tag is missing
        no_status = make_event(
            "ev_nostatus",
            30311,
            tags=[["title", "Planned Only"]],
            created_at=1700000000,
        )
        room = parse_nip53_event(no_status)
        self.assertEqual(room["status"], "planned")
        # Malformed tags container must not crash parsing
        room = parse_nip53_event({"kind": 30311, "tags": None})
        self.assertEqual(room["status"], "planned")


class FilterActiveLiveRoomsTests(TestCase):
    def test_deduplicates_by_pubkey_and_d_tag_preserving_latest_state(self):
        older = live_room_event(
            "ev_older",
            d_tag="same-room",
            title="Stale Title",
            status="planned",
            participants=1,
            pubkey=VALID_PUBKEY_HEX,
            created_at=1700000000,
        )
        newer = live_room_event(
            "ev_newer",
            d_tag="same-room",
            title="Fresh Title",
            status="live",
            participants=25,
            pubkey=VALID_PUBKEY_HEX,
            created_at=1700000100,
        )

        rooms = filter_active_live_rooms([older, newer])

        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0]["id"], "ev_newer")
        self.assertEqual(rooms[0]["title"], "Fresh Title")
        self.assertEqual(rooms[0]["status"], "live")
        self.assertEqual(rooms[0]["current_participants"], 25)

    def test_keeps_distinct_pubkeys_under_same_d_tag(self):
        room_a = live_room_event("ev_a", d_tag="shared", pubkey=VALID_PUBKEY_HEX)
        room_b = live_room_event("ev_b", d_tag="shared", pubkey=SECOND_PUBKEY_HEX)

        rooms = filter_active_live_rooms([room_a, room_b])

        self.assertEqual(len(rooms), 2)

    def test_orders_live_first_then_by_participant_count_descending(self):
        planned_busy = live_room_event("ev_planned", d_tag="p", title="Planned", status="planned", participants=40, pubkey=VALID_PUBKEY_HEX)
        live_quiet = live_room_event("ev_live_a", d_tag="la", title="Live A", status="live", participants=1, pubkey=SECOND_PUBKEY_HEX)
        live_busy = live_room_event("ev_live_b", d_tag="lb", title="Live B", status="live", participants=33, pubkey=VALID_PUBKEY_HEX)

        rooms = filter_active_live_rooms([planned_busy, live_quiet, live_busy])

        self.assertEqual([r["id"] for r in rooms], ["ev_live_b", "ev_live_a", "ev_planned"])

    def test_filters_out_malformed_and_wrong_kind_events(self):
        good = live_room_event("ev_good", d_tag="g", title="Good", status="live", pubkey=VALID_PUBKEY_HEX)
        malformed = [
            "junk",
            42,
            None,
            {"kind": 30312, "tags": [["title", "Wrong kind"]]},
            make_event("ev_kind1", 1),
        ]

        rooms = filter_active_live_rooms([good] + malformed)

        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0]["id"], "ev_good")


class LiveRoomsFeedViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="did:iyou:0x30311feedviewtest")
        self.client.force_login(self.user)

    def test_feed_renders_live_rooms_fallback_when_relays_return_empty(self):
        with patch("apps.core.views.relay_req", return_value={}):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="live-rooms-card"')
        self.assertContains(response, "No live audio spaces active on mesh.")

    def test_feed_renders_live_rooms_fallback_when_relays_return_malformed(self):
        def fake_relay_req(filter_obj, **kwargs):
            if filter_obj.get("kinds") == [30311]:
                return ["garbage", None, {"kind": 1}]
            return {}

        with patch("apps.core.views.relay_req", side_effect=fake_relay_req):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No live audio spaces active on mesh.")

    def test_feed_renders_live_rooms_widget_with_rooms(self):
        def fake_relay_req(filter_obj, **kwargs):
            if filter_obj.get("kinds") == [30311]:
                return {
                    "room_1": live_room_event(
                        "room_1",
                        d_tag="demo-spaces",
                        title="Demo Live Space",
                        streaming="https://cdn.iyou.me/demo.m3u8",
                        status="live",
                        participants=7,
                    )
                }
            return {}

        with patch("apps.core.views.relay_req", side_effect=fake_relay_req):
            response = self.client.get(reverse("feed"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="live-rooms-card"', content)
        self.assertIn("Demo Live Space", content)
        self.assertIn("LIVE", content)
        self.assertIn("Tune In", content)
        self.assertIn("data-stream-url=\"https://cdn.iyou.me/demo.m3u8\"", content)

    def test_feed_instant_shell_skips_live_rooms_probe(self):
        with patch("apps.core.views.relay_req", return_value={}) as mock_relay:
            response = self.client.get(reverse("feed") + "?async=1")

        self.assertEqual(response.status_code, 200)
        mock_relay.assert_not_called()
        self.assertEqual(response.context["live_rooms"], [])

    def test_sync_feed_probes_kind_30311_for_live_rooms(self):
        def fake_relay_req(filter_obj, **kwargs):
            if filter_obj.get("kinds") == [30311]:
                return {
                    "room_sync": live_room_event(
                        "room_sync",
                        d_tag="sync-radio",
                        title="Sync Radio",
                        streaming="https://cdn.iyou.me/sync.m3u8",
                        status="live",
                        participants=3,
                    )
                }
            return {}

        with patch("apps.core.views.relay_req", side_effect=fake_relay_req):
            response = self.client.get(reverse("feed") + "?sync=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["live_rooms"][0]["title"], "Sync Radio")