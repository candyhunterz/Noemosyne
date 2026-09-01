"""Small, explicit test object factories."""

from datetime import UTC, datetime
from uuid import uuid4

from noemosyne_domain.models import ClaimVersion


def claim_version() -> ClaimVersion:
    """Return a valid scope-qualified claim version."""
    return ClaimVersion(
        claim_id=uuid4(),
        wording="A scope-qualified test claim.",
        scope={"task_distribution": "test fixtures"},
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),
    )
