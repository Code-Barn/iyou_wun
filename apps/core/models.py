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

from django.conf import settings
from django.db import models


class IssuedCredential(models.Model):
    subject_did = models.CharField(max_length=512, db_index=True)
    credential_type = models.CharField(max_length=128)
    vc_id = models.CharField(max_length=512, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return f"<IssuedCredential {self.vc_id} -> {self.subject_did}>"


class UserLinkDeck(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="link_deck",
    )
    handle = models.CharField(max_length=32, db_index=True)
    discriminator = models.PositiveIntegerField(default=0)
    display_name = models.CharField(max_length=100, blank=True, default="")
    headline = models.CharField(max_length=160, blank=True, default="")
    avatar_url = models.CharField(max_length=2048, blank=True, default="")
    banner_url = models.CharField(max_length=2048, blank=True, default="")
    nip05 = models.CharField(max_length=300, blank=True, default="")
    lud16 = models.CharField(max_length=300, blank=True, default="")
    nostr_pubkey = models.CharField(max_length=64, blank=True, default="", db_index=True)

    default_view = models.CharField(
        max_length=8,
        choices=[("deck", "deck"), ("feed", "feed")],
        default="deck",
    )
    is_public = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    verified_source_url = models.CharField(max_length=512, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["handle", "discriminator"], name="uniq_handle_disc")
        ]

    def __str__(self):
        return f"<UserLinkDeck {self.display_handle()} -> {self.user.username}>"

    @property
    def display_handle(self):
        if self.discriminator == 0:
            return f"@{self.handle}"
        return f"@{self.handle}[{self.discriminator}]"

    @property
    def canonical_path(self):
        return f"/{self.display_handle}"

    def save(self, *args, **kwargs):
        """Automatically derive NIP-05 address from handle and discriminator."""
        if self.handle:
            clean_handle = self.handle.lower().lstrip("@").strip()
            if self.discriminator and self.discriminator > 0:
                self.nip05 = f"{clean_handle}_{self.discriminator}@iyou.me"
            else:
                self.nip05 = f"{clean_handle}@iyou.me"
        if "update_fields" in kwargs and kwargs["update_fields"] is not None:
            kwargs["update_fields"] = list(set(kwargs["update_fields"]) | {"nip05"})
        super().save(*args, **kwargs)


class UserLinkItem(models.Model):
    ICON_CATEGORY_CHOICES = [
        ("x", "X"),
        ("github", "GitHub"),
        ("mastodon", "Mastodon"),
        ("website", "Website"),
        ("blog", "Blog"),
        ("talk", "Talk"),
        ("poly", "Poly"),
        ("gallery", "Gallery"),
        ("link", "Link"),
    ]

    deck = models.ForeignKey(UserLinkDeck, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=64)
    url = models.CharField(max_length=2048)
    icon_category = models.CharField(
        max_length=20, choices=ICON_CATEGORY_CHOICES, default="link"
    )
    is_ecosystem_link = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"<UserLinkItem {self.title} -> {self.url}>"

    @property
    def icon_emoji(self):
        return ICON_EMOJIS.get(self.icon_category, "🔗")


ICON_EMOJIS = {
    "x": "\U0001D54F",
    "github": "\U0001F4BB",
    "mastodon": "\U0001F418",
    "website": "\U0001F310",
    "blog": "\u270D\uFE0F",
    "talk": "\U0001F4AC",
    "poly": "\U0001F5F3\uFE0F",
    "gallery": "\U0001F5BC\uFE0F",
    "link": "\U0001F517",
}


class HandleVerificationChallenge(models.Model):
    deck = models.ForeignKey(
        UserLinkDeck, on_delete=models.CASCADE, related_name="challenges"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    target_handle = models.CharField(max_length=32)
    external_url = models.CharField(max_length=512, blank=True, default="")
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"<HandleVerificationChallenge {self.target_handle} via {self.external_url}>"

    @property
    def is_expired(self):
        from django.utils import timezone
        return self.expires_at <= timezone.now()


class NodeBlockedEntity(models.Model):
    REASON_CHOICES = [
        ("ILLEGAL_CSAM", "Illegal Content"),
        ("MALWARE", "Malware"),
        ("HARASSMENT", "Severe Harassment"),
        ("SPAM_BOT", "Automated Spam"),
        ("ADMIN_OVERRIDE", "Operator Emergency Discretion"),
    ]

    entity_identifier = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Pubkey hex (64 chars) or DID string to suppress.",
    )
    reason = models.CharField(
        max_length=32,
        choices=REASON_CHOICES,
        default="ADMIN_OVERRIDE",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Node Blocked Entity"
        verbose_name_plural = "Node Blocked Entities"

    def __str__(self):
        return f"<NodeBlockedEntity {self.entity_identifier} ({self.reason}) active={self.is_active}>"


class NodeContentTakedown(models.Model):
    event_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        db_index=True,
        help_text="Nostr Event ID (64-hex).",
    )
    media_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="Blossom media SHA-256 hash (64-hex).",
    )
    reason = models.CharField(
        max_length=32,
        choices=NodeBlockedEntity.REASON_CHOICES,
        default="ADMIN_OVERRIDE",
    )
    purged_from_blossom = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Node Content Takedown"
        verbose_name_plural = "Node Content Takedowns"

    def __str__(self):
        target = self.event_id or self.media_hash or "unknown"
        return f"<NodeContentTakedown {target} ({self.reason}) purged={self.purged_from_blossom}>"
