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

from django.contrib import admin

from .models import IssuedCredential


@admin.register(IssuedCredential)
class IssuedCredentialAdmin(admin.ModelAdmin):
    list_display = ("vc_id", "subject_did", "credential_type", "issued_at")
    list_filter = ("credential_type", "issued_at")
    search_fields = ("subject_did", "vc_id")
    readonly_fields = ("subject_did", "credential_type", "vc_id", "issued_at")
