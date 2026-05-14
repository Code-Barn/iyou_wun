### 🏛️ The "Meshing" Protocol: Integration Plan

Use this standard workflow whenever you bring a new Django or React app into the ecosystem.

#### Phase 1: Identity Swap (The OIDC Handshake)

- **Django Core**: Install `mozilla-django-oidc`.

- **Backend Replacement**: Swap out `ModelBackend` for our custom `MyOIDCAuthenticationBackend`.

- **Mapping**: The `sub` claim from the IdP is the **DID**. This must be the unique primary key for the User model across all apps.

- **Security**: Set `SESSION\_COOKIE\_NAME` and `CSRF\_COOKIE\_NAME` to be unique (e.g., `hiver\_sessionid`).

#### Phase 2: Mesh Awareness (The UI Bridge)

- **Floating Header**: Import the unified `\_nav.html` template.

- **The Probe**: Add the JS heartbeat that checks port `9001` for the "Sovereign Mesh Active" badge.

- **The Switcher**: Ensure the app-switcher menu includes links to WUN, Polly, and the new app.

#### Phase 3: Protocol Signatures (The Vault Pipe)

- **React/JS Apps**: Import the `sendEventToTauri` WebSocket utility.

- **Custom Message Types**:

  - **Hiver**: Needs a `sign\_evidence` or `sign\_claim` message type.

  - **Polly**: Already uses `sign\_credential`.

  - **WUN**: Uses `sign\_event` (Nostr).

- **The Result**: The app generates a JSON payload (a hash of a legal document in Hiver's case), sends it to the bridge, and stores the resulting cryptographic proof in the database.

