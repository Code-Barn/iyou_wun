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

import logging

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .models import NodeBlockedEntity, NodeContentTakedown
from .moderation import invalidate_shield_cache, purge_blossom_blob

logger = logging.getLogger(__name__)


@user_passes_test(lambda u: u.is_authenticated and u.is_staff)
@require_http_methods(["GET", "POST"])
def moderation_console(request):
    """
    Administrative moderation desk for sovereign node operators.
    Enforces instance-level defensive kill-switch, content takedowns, and Blossom blob scrubbing.
    Access is restricted exclusively to operators evaluated as staff via ADMIN_DID posture.
    """
    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "block_entity":
            entity_identifier = request.POST.get("entity_identifier", "").strip()
            reason = request.POST.get("reason", "ADMIN_OVERRIDE").strip()
            notes = request.POST.get("notes", "").strip()

            if entity_identifier:
                NodeBlockedEntity.objects.update_or_create(
                    entity_identifier=entity_identifier,
                    defaults={
                        "reason": reason,
                        "notes": notes,
                        "is_active": True,
                    },
                )
                invalidate_shield_cache()
                messages.success(request, f"Entity '{entity_identifier[:32]}...' blocked successfully ({reason}).")
                logger.info(
                    "Admin %s blocked entity %s (reason: %s)",
                    request.user.username,
                    entity_identifier,
                    reason,
                )
            else:
                messages.error(request, "Entity identifier (pubkey hex or DID) is required.")

        elif action == "unblock_entity":
            entity_id = request.POST.get("entity_id")
            entity_identifier = request.POST.get("entity_identifier", "").strip()

            qs = NodeBlockedEntity.objects.all()
            if entity_id:
                qs = qs.filter(id=entity_id)
            elif entity_identifier:
                qs = qs.filter(entity_identifier=entity_identifier)
            else:
                qs = qs.none()

            deleted_count, _ = qs.delete()
            if deleted_count > 0:
                invalidate_shield_cache()
                messages.success(request, "Entity block successfully revoked.")
                logger.info("Admin %s unblocked entity (deleted %s records)", request.user.username, deleted_count)
            else:
                messages.warning(request, "Target entity block not found or already revoked.")

        elif action == "takedown_event":
            event_id = request.POST.get("event_id", "").strip()
            reason = request.POST.get("reason", "ADMIN_OVERRIDE").strip()

            if event_id:
                NodeContentTakedown.objects.update_or_create(
                    event_id=event_id,
                    defaults={
                        "reason": reason,
                    },
                )
                invalidate_shield_cache()
                messages.success(request, f"Event '{event_id[:32]}...' taken down ({reason}).")
                logger.info("Admin %s executed takedown on event %s (reason: %s)", request.user.username, event_id, reason)
            else:
                messages.error(request, "Nostr Event ID (64-hex) is required.")

        elif action == "purge_media":
            media_hash = request.POST.get("media_hash", "").strip()
            reason = request.POST.get("reason", "ADMIN_OVERRIDE").strip()
            blossom_host = request.POST.get("blossom_host", "http://127.0.0.1:9002").strip()

            if media_hash:
                purged = purge_blossom_blob(media_hash, blossom_host=blossom_host)
                NodeContentTakedown.objects.update_or_create(
                    media_hash=media_hash,
                    defaults={
                        "reason": reason,
                        "purged_from_blossom": purged,
                    },
                )
                invalidate_shield_cache()
                if purged:
                    messages.success(
                        request,
                        f"Media '{media_hash[:32]}...' successfully purged from Blossom daemon and blacklisted ({reason}).",
                    )
                else:
                    messages.warning(
                        request,
                        f"Media '{media_hash[:32]}...' blacklisted locally, but Blossom daemon returned an error during purge.",
                    )
                logger.info(
                    "Admin %s purged media %s (purged: %s, reason: %s)",
                    request.user.username,
                    media_hash,
                    purged,
                    reason,
                )
            else:
                messages.error(request, "Media SHA-256 hash (64-hex) is required.")

        elif action in ("revoke_takedown", "delete_takedown"):
            takedown_id = request.POST.get("takedown_id")
            if takedown_id:
                NodeContentTakedown.objects.filter(id=takedown_id).delete()
                invalidate_shield_cache()
                messages.success(request, "Content takedown revoked.")
                logger.info("Admin %s revoked takedown id %s", request.user.username, takedown_id)

        return redirect("moderation_console")

    # Pass the 25 most recent takedowns and blocked entities to the template
    blocked_entities = NodeBlockedEntity.objects.filter(is_active=True).order_by("-created_at")[:25]
    recent_takedowns = NodeContentTakedown.objects.all().order_by("-created_at")[:25]

    context = {
        "blocked_entities": blocked_entities,
        "recent_takedowns": recent_takedowns,
        "reason_choices": NodeBlockedEntity.REASON_CHOICES,
        "total_blocked_count": NodeBlockedEntity.objects.filter(is_active=True).count(),
        "total_takedown_count": NodeContentTakedown.objects.count(),
    }
    return render(request, "admin/moderation_desk.html", context)
