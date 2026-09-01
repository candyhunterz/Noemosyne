"""Epistemic-specific test assertions."""

from typing import Any


def assert_provenance(record: Any) -> None:
    """Assert that a canonical record can be traced to its accepted proposal item."""
    assert record.proposal_item_id
    assert record.status == "accepted"
