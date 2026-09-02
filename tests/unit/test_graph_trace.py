from noemosyne_db.models import ClaimRelation
from noemosyne_retrieval.graph_trace import trace_claim_graph


def _add_relation(session, source: str, target: str, relation_type: str = "depends_on") -> str:
    relation = ClaimRelation(
        source_claim_id=source,
        target_claim_id=target,
        relation_type=relation_type,
        context_json={},
        reviewer_actor_id="reviewer",
        status="accepted",
        proposal_item_id="item",
    )
    session.add(relation)
    session.flush()
    return relation.id


def _trace(session, start: str = "a", max_depth: int = 3, max_nodes: int = 100):
    session.commit()
    return trace_claim_graph(session, start, {"depends_on", "entails"}, max_depth, max_nodes)


def test_one_edge_is_emitted_once_at_minimum_depth(session) -> None:
    edge_id = _add_relation(session, "a", "b")

    result = _trace(session)

    assert result == {
        "nodes": ["a", "b"],
        "edges": [{"id": edge_id, "source": "a", "target": "b", "type": "depends_on", "depth": 1}],
        "truncated": False,
    }


def test_linear_chain_records_minimum_discovery_depth(session) -> None:
    first = _add_relation(session, "a", "b")
    second = _add_relation(session, "b", "c")
    third = _add_relation(session, "c", "d")

    result = _trace(session)

    assert result["nodes"] == ["a", "b", "c", "d"]
    assert [(edge["id"], edge["depth"]) for edge in result["edges"]] == [
        (first, 1),
        (second, 2),
        (third, 3),
    ]


def test_two_node_cycle_does_not_repeat_edges_or_expand_again(session) -> None:
    _add_relation(session, "a", "b")
    _add_relation(session, "b", "a", "entails")

    result = _trace(session)

    assert result["nodes"] == ["a", "b"]
    assert len(result["edges"]) == 2
    assert {edge["depth"] for edge in result["edges"]} == {1}
    assert len({edge["id"] for edge in result["edges"]}) == 2


def test_larger_cycle_terminates_with_each_edge_once(session) -> None:
    _add_relation(session, "a", "b")
    _add_relation(session, "b", "c")
    _add_relation(session, "c", "d")
    _add_relation(session, "d", "a")

    result = _trace(session)

    assert result["nodes"] == ["a", "b", "c", "d"]
    assert len(result["edges"]) == 4
    assert len({edge["id"] for edge in result["edges"]}) == 4
    assert max(edge["depth"] for edge in result["edges"]) == 2


def test_multiple_edges_between_visited_nodes_are_each_emitted_once(session) -> None:
    _add_relation(session, "a", "b", "depends_on")
    _add_relation(session, "a", "b", "entails")

    result = _trace(session)

    assert len(result["edges"]) == 2
    assert {edge["type"] for edge in result["edges"]} == {"depends_on", "entails"}


def test_duplicate_paths_discover_node_once_but_keep_distinct_edges(session) -> None:
    _add_relation(session, "a", "b")
    _add_relation(session, "a", "c")
    _add_relation(session, "b", "d")
    _add_relation(session, "c", "d")

    result = _trace(session)

    assert result["nodes"] == ["a", "b", "c", "d"]
    assert len(result["edges"]) == 4
    assert [edge["depth"] for edge in result["edges"]].count(2) == 2


def test_node_limit_sets_truncated_only_when_discovery_is_prevented(session) -> None:
    kept = _add_relation(session, "a", "b")
    _add_relation(session, "a", "c")

    result = _trace(session, max_nodes=2)

    assert result["nodes"] == ["a", "b"]
    assert [edge["id"] for edge in result["edges"]] == [kept]
    assert result["truncated"] is True


def test_reaching_node_limit_without_an_omitted_node_is_not_truncated(session) -> None:
    _add_relation(session, "a", "b")

    result = _trace(session, max_nodes=2)

    assert result["nodes"] == ["a", "b"]
    assert result["truncated"] is False


def test_disallowed_relation_types_are_not_returned(session) -> None:
    _add_relation(session, "a", "b")
    session.commit()

    result = trace_claim_graph(session, "a", {"related_to"}, 3, 100)

    assert result == {"nodes": ["a"], "edges": [], "truncated": False}


def test_repeated_traces_are_deterministic(session) -> None:
    _add_relation(session, "c", "d")
    _add_relation(session, "a", "c", "entails")
    _add_relation(session, "a", "b")
    session.commit()

    first = trace_claim_graph(session, "a", {"depends_on", "entails"}, 3, 100)
    second = trace_claim_graph(session, "a", {"depends_on", "entails"}, 3, 100)

    assert first == second
    assert len({edge["id"] for edge in first["edges"]}) == len(first["edges"])
