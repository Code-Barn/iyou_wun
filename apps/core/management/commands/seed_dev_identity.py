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

"""Seed the local dev database with the @dcbyers13 identity.

``@dcbyers13`` is the handle the owner uses against the production cluster at
wun.iyou.me. It is absent from a fresh local ``db.sqlite3``, so
``/profile/dcbyers13/`` reports "Peer Not Found on Mesh" locally and the profile
page cannot be exercised during development.

This command creates the owning ``User`` (keyed by the production DID) and its
``UserLinkDeck`` so local resolution takes the same path it does in production.

It is idempotent: re-running updates the existing deck in place rather than
creating a duplicate, and never touches a deck that already claims the handle
under a different owner unless ``--force`` is passed.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import UserLinkDeck

# The production owner DID for @dcbyers13. This is an Ed25519 did:key, so
# did_to_pubkey() yields the enclave-transition author value rather than a
# secp256k1 point; _resolve_profile_candidates queries it as an author candidate
# so locally seeded notes resolve the same way they do in production.
OWNER_DID = "did:key:z6MkujsSdMm1j7QqUNaZo8U8kkcJNfFNikUQYJzmZX4wwgND"
HANDLE = "dcbyers13"
DISPLAY_NAME = "David Byers"
NIP05 = "dcbyers13@wun.iyou.me"


class Command(BaseCommand):
    help = "Seed the local dev DB with the @dcbyers13 UserLinkDeck (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--handle",
            default=HANDLE,
            help="Handle to claim (default: %(default)s).",
        )
        parser.add_argument(
            "--did",
            default=OWNER_DID,
            help="Owning user DID (default: the production @dcbyers13 DID).",
        )
        parser.add_argument(
            "--nostr-pubkey",
            default="",
            help=(
                "Optional 64-char hex Nostr key to store on the deck. Leave empty "
                "to reproduce production, where this deck has no synced key and "
                "resolves via its DID-derived author candidate."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Reassign the handle if it is already owned by a different user.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        handle = options["handle"].strip().lower()
        did = options["did"].strip()
        nostr_pubkey = (options["nostr_pubkey"] or "").strip().lower()

        if nostr_pubkey and len(nostr_pubkey) != 64:
            raise CommandError(
                "--nostr-pubkey must be 64 hex chars, got %d." % len(nostr_pubkey)
            )

        User = get_user_model()
        user, user_created = User.objects.get_or_create(username=did)
        if user_created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS("created user %s" % did))
        else:
            self.stdout.write("user %s already exists" % did)

        # UserLinkDeck.user is a OneToOneField: a user owns exactly one deck, so
        # this must be looked up by HANDLE. Looking it up by user would return
        # whatever deck that user already has and silently rename it -- which is
        # exactly how an earlier version of this command clobbered an existing
        # handle.
        deck = UserLinkDeck.objects.filter(handle__iexact=handle).order_by("discriminator", "pk").first()
        created = False

        if deck and deck.user_id != user.pk and not options["force"]:
            raise CommandError(
                "handle @%s is already owned by %s; pass --force to reassign."
                % (handle, deck.user.username)
            )

        if deck is None:
            # The user may already own a deck under a different handle. Since the
            # relation is one-to-one we cannot add a second one, so say so rather
            # than renaming their existing deck behind their back. With --force we
            # rename that deck in place -- creating a fresh row would violate the
            # one-to-one constraint on user_id.
            owned = UserLinkDeck.objects.filter(user=user).first()
            if owned:
                if not options["force"]:
                    raise CommandError(
                        "%s already owns @%s, and UserLinkDeck.user is one-to-one so a "
                        "user can hold only one deck. Refusing to rename it. Re-run with "
                        "--force to move that deck to @%s, or pass --did with a different "
                        "owner DID." % (did, owned.handle, handle)
                    )
                deck = owned
            else:
                deck = UserLinkDeck(user=user, handle=handle)
                created = True

        if deck.user_id != user.pk:
            deck.user = user

        changed = []
        if deck.handle != handle:
            deck.handle = handle
            changed.append("handle")
        if not deck.display_name:
            deck.display_name = DISPLAY_NAME
            changed.append("display_name")
        if not deck.nip05:
            deck.nip05 = NIP05
            changed.append("nip05")
        if nostr_pubkey and deck.nostr_pubkey != nostr_pubkey:
            deck.nostr_pubkey = nostr_pubkey
            changed.append("nostr_pubkey")

        if created:
            deck.save()
        elif changed:
            deck.save(update_fields=["user"] + changed + ["updated_at"])
        else:
            deck.save(update_fields=["user"])

        verb = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                "%s deck @%s -> %s (nostr_pubkey=%s)"
                % (verb, deck.handle, deck.user.username, deck.nostr_pubkey or "(none, DID-derived)")
            )
        )
        self.stdout.write("resolve /profile/%s/ locally to verify" % deck.handle)
