from datetime import UTC, datetime, timedelta
from pathlib import Path

from noemosyne_db.models import AuditEvent, Base, Claim, ClaimVersion, EpistemicAssessment
from noemosyne_db.seed import export_seed, import_seed
from noemosyne_retrieval.context_bundle import build_context_bundle
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_seed_is_idempotent_and_context_has_no_temporal_leakage(session) -> None:
    path = Path("examples/ai-research/seed.yaml")
    first = import_seed(session, path)
    second = import_seed(session, path)
    assert first["status"] == "imported"
    assert second["status"] == "noop"
    assert session.query(AuditEvent).filter_by(event_type="seed.imported").count() == 1

    claim = session.scalar(select(Claim).order_by(Claim.id))
    assert claim is not None
    before_import = datetime.now(UTC) - timedelta(days=1)
    assert build_context_bundle(session, claim.id, before_import, before_import) is None
    now = datetime.now(UTC) + timedelta(seconds=1)
    bundle = build_context_bundle(session, claim.id, now, now)
    assert bundle is not None
    assert bundle["claim"]["id"] == claim.id


def test_all_seed_assessments_have_inputs(session) -> None:
    import_seed(session, Path("examples/ai-research/seed.yaml"))
    assessments = session.scalars(select(EpistemicAssessment)).all()
    assert assessments
    for assessment in assessments:
        assert assessment.verdict != "unassessed"


def test_seed_export_import_round_trip_preserves_claim_semantics(session, tmp_path) -> None:
    source = Path("examples/ai-research/seed.yaml")
    first = import_seed(session, source)
    exported = tmp_path / "round-trip.yaml"
    identity = f"{first['package_id']}@{first['version']}"
    report = export_seed(session, identity, exported)
    assert report["sha256"] == first["sha256"]

    second_engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(second_engine)
    with Session(second_engine) as second_session:
        second = import_seed(second_session, exported)
        original_wording = sorted(session.scalars(select(ClaimVersion.wording)).all())
        restored_wording = sorted(second_session.scalars(select(ClaimVersion.wording)).all())
        assert second["sha256"] == first["sha256"]
        assert restored_wording == original_wording
