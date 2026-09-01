from noemosyne_db.models import ClaimRelation
from noemosyne_retrieval.graph_trace import trace_claim_graph


def test_graph_trace_is_allowlisted_and_bounded(session) -> None:
    for index in range(120):
        session.add(
            ClaimRelation(
                source_claim_id="root",
                target_claim_id=f"claim-{index}",
                relation_type="depends_on",
                context_json={},
                reviewer_actor_id="reviewer",
                status="accepted",
                proposal_item_id="item",
            )
        )
    session.commit()
    result = trace_claim_graph(session, "root", {"depends_on", "related_to"}, 3, 100)
    assert len(result["nodes"]) <= 100
    assert all(edge["type"] == "depends_on" for edge in result["edges"])
