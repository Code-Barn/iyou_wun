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

from collections import Counter
import logging

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .models import (
    CommunityFlagLedger,
    ModerationAppeal,
    ModerationReviewDocket,
    NodeBlockedEntity,
    NodeContentTakedown,
)
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

        elif action == "docket_confirm":
            docket_id = request.POST.get("docket_id")
            target_identifier = request.POST.get("target_identifier", "").strip()

            docket = None
            if docket_id:
                docket = ModerationReviewDocket.objects.filter(id=docket_id).first()
            elif target_identifier:
                docket = ModerationReviewDocket.objects.filter(target_identifier=target_identifier).first()

            if docket:
                docket.status = "CONFIRMED"
                docket.reviewed_by_did = request.user.username
                docket.save(update_fields=["status", "reviewed_by_did", "updated_at"])

                if docket.docket_type == "pubkey":
                    NodeBlockedEntity.objects.update_or_create(
                        entity_identifier=docket.target_identifier,
                        defaults={
                            "reason": "ADMIN_OVERRIDE",
                            "notes": f"Confirmed from Community Review Docket (flags: {docket.flag_count})",
                            "is_active": True,
                        },
                    )
                else:
                    NodeContentTakedown.objects.update_or_create(
                        event_id=docket.target_identifier,
                        defaults={
                            "reason": "ADMIN_OVERRIDE",
                        },
                    )

                invalidate_shield_cache()
                messages.success(
                    request,
                    f"Docket '{docket.target_identifier[:32]}...' confirmed and elevated to permanent safe harbor suppression.",
                )
                logger.info(
                    "Admin %s confirmed review docket %s (type: %s)",
                    request.user.username,
                    docket.target_identifier,
                    docket.docket_type,
                )
            else:
                messages.error(request, "Review docket target not found.")

        elif action == "docket_dismiss":
            docket_id = request.POST.get("docket_id")
            target_identifier = request.POST.get("target_identifier", "").strip()

            docket = None
            if docket_id:
                docket = ModerationReviewDocket.objects.filter(id=docket_id).first()
            elif target_identifier:
                docket = ModerationReviewDocket.objects.filter(target_identifier=target_identifier).first()

            if docket:
                docket.status = "DISMISSED"
                docket.reviewed_by_did = request.user.username
                docket.save(update_fields=["status", "reviewed_by_did", "updated_at"])

                invalidate_shield_cache()
                messages.success(
                    request,
                    f"Docket '{docket.target_identifier[:32]}...' dismissed. Content/entity restored to public view.",
                )
                logger.info(
                    "Admin %s dismissed review docket %s (type: %s)",
                    request.user.username,
                    docket.target_identifier,
                    docket.docket_type,
                )
            else:
                messages.error(request, "Review docket target not found.")

        elif action == "appeal_resolve":
            appeal_id = request.POST.get("appeal_id")
            decision = request.POST.get("decision", "").strip().lower()

            appeal = None
            if appeal_id:
                try:
                    appeal = ModerationAppeal.objects.select_related("docket").get(id=int(appeal_id))
                except (ModerationAppeal.DoesNotExist, ValueError):
                    appeal = None

            if appeal:
                docket = appeal.docket
                if decision in ("accept", "accepted"):
                    appeal.status = "ACCEPTED"
                    appeal.reviewed_by_did = request.user.username
                    appeal.save(update_fields=["status", "reviewed_by_did", "updated_at"])

                    if docket:
                        docket.status = "DISMISSED"
                        docket.reviewed_by_did = request.user.username
                        docket.save(update_fields=["status", "reviewed_by_did", "updated_at"])

                    invalidate_shield_cache()
                    messages.success(
                        request,
                        f"Appeal #{appeal.id} accepted. Restored target '{docket.target_identifier[:32] if docket else ''}' and cleared instance friction.",
                    )
                    logger.info(
                        "Admin %s accepted moderation appeal #%s for docket #%s (%s)",
                        request.user.username,
                        appeal.id,
                        docket.id if docket else None,
                        docket.target_identifier if docket else "",
                    )
                elif decision in ("reject", "rejected"):
                    appeal.status = "REJECTED"
                    appeal.reviewed_by_did = request.user.username
                    appeal.save(update_fields=["status", "reviewed_by_did", "updated_at"])

                    invalidate_shield_cache()
                    messages.warning(
                        request,
                        f"Appeal #{appeal.id} rejected. Enforcement maintained on '{docket.target_identifier[:32] if docket else ''}'.",
                    )
                    logger.info(
                        "Admin %s rejected moderation appeal #%s for docket #%s",
                        request.user.username,
                        appeal.id,
                        docket.id if docket else None,
                    )
                else:
                    messages.error(request, f"Invalid decision '{decision}'. Expected 'accept' or 'reject'.")
            else:
                messages.error(request, "Target appeal not found.")

        return redirect("moderation_console")

    # Pass the 25 most recent takedowns, blocked entities, and pending review dockets
    blocked_entities = NodeBlockedEntity.objects.filter(is_active=True).order_by("-created_at")[:25]
    recent_takedowns = NodeContentTakedown.objects.all().order_by("-created_at")[:25]
    pending_dockets = list(
        ModerationReviewDocket.objects.filter(status="PENDING")
        .prefetch_related("appeals")
        .order_by("-flag_count")[:50]
    )

    for d in pending_dockets:
        if d.docket_type == "event":
            flags = CommunityFlagLedger.objects.filter(target_event_id=d.target_identifier).values_list("reason", flat=True)
        else:
            flags = CommunityFlagLedger.objects.filter(target_pubkey=d.target_identifier).values_list("reason", flat=True)
        d.reasons_summary = dict(Counter(flags))
        d.active_appeal = next((a for a in d.appeals.all() if a.status == "PENDING"), None)

    context = {
        "blocked_entities": blocked_entities,
        "recent_takedowns": recent_takedowns,
        "pending_dockets": pending_dockets,
        "reason_choices": NodeBlockedEntity.REASON_CHOICES,
        "total_blocked_count": NodeBlockedEntity.objects.filter(is_active=True).count(),
        "total_takedown_count": NodeContentTakedown.objects.count(),
        "total_docket_count": ModerationReviewDocket.objects.filter(status="PENDING").count(),
    }
    return render(request, "admin/moderation_desk.html", context)
