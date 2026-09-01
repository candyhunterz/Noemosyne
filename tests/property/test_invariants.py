from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st
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
