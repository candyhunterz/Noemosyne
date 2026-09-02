import runpy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st
from noemosyne_db.models import Base, CanonicalMixin
from noemosyne_domain.models import (
    ALLOWED_RELATIONS,
    Verdict,
    validate_assessment_inputs,
    validate_relation,
)


@given(st.sampled_from(sorted(ALLOWED_RELATIONS - {"incompatible_with"})))
def test_allowlisted_relations_accept_explicit_vocabulary(relation: str) -> None:
    validate_relation(relation, {})


@given(
    st.datetimes(timezones=st.just(UTC)),
    st.timedeltas(min_value=timedelta(microseconds=1), max_value=timedelta(days=365)),
)
def test_historical_cutoff_excludes_later_recorded_times(
    cutoff: datetime, delta: timedelta
) -> None:
    assert not (cutoff + delta <= cutoff)


@given(st.sampled_from([verdict for verdict in Verdict if verdict is not Verdict.UNASSESSED]))
def test_every_substantive_assessment_accepts_inspectable_input(verdict: Verdict) -> None:
    validate_assessment_inputs(verdict, (uuid4(),))


def test_every_canonical_table_is_covered_by_deferred_process_provenance() -> None:
    migration = runpy.run_path("migrations/versions/0004_process_provenance.py")
    canonical_tables = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, CanonicalMixin)
    }

    assert canonical_tables == set(migration["CANONICAL_TABLES"])
    for mapper in Base.registry.mappers:
        if mapper.local_table.name not in canonical_tables:
            continue
        proposal_column = mapper.local_table.c.proposal_item_id
        foreign_key = next(iter(proposal_column.foreign_keys))
        assert foreign_key.deferrable is True
        assert foreign_key.initially == "DEFERRED"
