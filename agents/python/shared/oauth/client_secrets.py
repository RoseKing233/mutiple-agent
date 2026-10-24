"""Deterministic dev client-secret derivation.

Offline-first, fixed client registry: every first-party service shares one
``OAUTH_SEED_KEY`` knob (the same pattern ``AGENT_SHARED_SECRET`` already
uses), and each service's dev secret is derived from it plus the
service's own ``client_id`` — so the seeder and every service compute the
identical secret without a secrets round-trip. Production deployments
override ``OAUTH_CLIENT_SECRET`` per service instead of relying on this
derivation (see ``docs/security-guide.md``).
"""

from __future__ import annotations

import hmac
from hashlib import sha256


def derive_client_secret(seed_key: str, client_id: str) -> str:
    """HMAC-SHA256(seed_key, client_id), hex-encoded."""
    return hmac.new(seed_key.encode(), client_id.encode(), sha256).hexdigest()
