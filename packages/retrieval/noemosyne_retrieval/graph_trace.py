"""Bounded, allowlisted graph traversal over accepted claim relations."""

from __future__ import annotations

from typing import Any

from noemosyne_db.models import ClaimRelation
from noemosyne_domain.models import ALLOWED_RELATIONS
from sqlalchemy import or_, select
from sqlalchemy.orm import Session


def trace_claim_graph(
    session: Session,
    start_claim_id: str,
    relation_types: set[str],
    max_depth: int = 3,
    max_nodes: int = 100,
) -> dict[str, Any]:
    """Traverse accepted relations without exceeding hard product bounds."""
    allowed = relation_types & ALLOWED_RELATIONS
    depth_limit = min(max(max_depth, 0), 3)
    node_limit = min(max(max_nodes, 1), 100)
    visited = {start_claim_id}
    frontier = {start_claim_id}
    edges: list[dict[str, str | int]] = []
    for depth in range(1, depth_limit + 1):
        if not frontier or len(visited) >= node_limit:
            break
        rows = session.scalars(
            select(ClaimRelation)
            .where(
                ClaimRelation.status == "accepted",
                ClaimRelation.relation_type.in_(allowed),
                or_(
                    ClaimRelation.source_claim_id.in_(frontier),
                    ClaimRelation.target_claim_id.in_(frontier),
                ),
            )
            .order_by(
                ClaimRelation.relation_type,
                ClaimRelation.source_claim_id,
                ClaimRelation.target_claim_id,
            )
        ).all()
        next_frontier: set[str] = set()
        for row in rows:
            candidate = (
                row.target_claim_id if row.source_claim_id in frontier else row.source_claim_id
            )
            if candidate not in visited and len(visited) >= node_limit:
                continue
            visited.add(candidate)
            next_frontier.add(candidate)
            edges.append(
                {
                    "id": row.id,
                    "source": row.source_claim_id,
                    "target": row.target_claim_id,
                    "type": row.relation_type,
                    "depth": depth,
                }
            )
        frontier = next_frontier
    return {"nodes": sorted(visited), "edges": edges, "truncated": len(visited) >= node_limit}
