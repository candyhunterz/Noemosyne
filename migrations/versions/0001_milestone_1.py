"""Create the Milestone 1 canonical ledger.

Revision ID: 0001_milestone_1
Revises: None
"""

from __future__ import annotations

from alembic import op
from noemosyne_db.models import Base

revision = "0001_milestone_1"
down_revision = None
branch_labels = None
depends_on = None


APPEND_ONLY_TABLES = [
    "actors",
    "entities",
    "entity_aliases",
    "claims",
    "claim_versions",
    "claim_entities",
    "assertions",
    "source_artifacts",
    "source_fragments",
    "evidence_items",
    "evidence_item_sources",
    "evidence_dependency_groups",
    "evidence_dependency_members",
    "evidence_links",
    "arguments",
    "argument_premises",
    "challenges",
    "claim_relations",
    "assessment_policies",
    "epistemic_assessments",
    "assessment_inputs",
    "revision_events",
    "revision_impacts",
    "questions",
    "question_claims",
    "review_decisions",
    "audit_events",
]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_reject_any_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'ledger rows are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_reject_accepted_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'accepted'
             AND current_setting('noemosyne.accepting_proposal', true) IS DISTINCT FROM 'on' THEN
            RAISE EXCEPTION 'accepted ledger rows are append-only; supersede instead';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in APPEND_ONLY_TABLES:
        if table in {"actors", "review_decisions", "audit_events"}:
            op.execute(
                f"""
                CREATE TRIGGER {table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION noemosyne_reject_any_mutation()
                """
            )
            continue
        op.execute(
            f"""
            CREATE TRIGGER {table}_accepted_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION noemosyne_reject_accepted_mutation()
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_check_assessment_inputs()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'accepted' AND NEW.verdict <> 'unassessed'
             AND NOT EXISTS (
               SELECT 1 FROM assessment_inputs
               WHERE assessment_id = NEW.id AND status = 'accepted'
             ) THEN
            RAISE EXCEPTION 'a substantive assessment requires an accepted input';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE CONSTRAINT TRIGGER epistemic_assessments_require_inputs
        AFTER INSERT OR UPDATE ON epistemic_assessments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION noemosyne_check_assessment_inputs();

        CREATE OR REPLACE FUNCTION noemosyne_check_claim_current_version()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'accepted' AND NEW.current_version_id IS NULL THEN
            RAISE EXCEPTION 'an accepted claim requires a current version';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE CONSTRAINT TRIGGER claims_require_current_version
        AFTER INSERT OR UPDATE ON claims
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION noemosyne_check_claim_current_version();

        CREATE OR REPLACE FUNCTION noemosyne_check_relation_context()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'accepted' AND NEW.relation_type = 'incompatible_with'
             AND NEW.context_json::text IN ('{}', 'null') THEN
            RAISE EXCEPTION 'incompatible_with requires explicit overlap context';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER claim_relations_require_context
        BEFORE INSERT OR UPDATE ON claim_relations
        FOR EACH ROW EXECUTE FUNCTION noemosyne_check_relation_context();

        CREATE OR REPLACE FUNCTION noemosyne_check_fragment_locator()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.locator_json::text IN ('{}', 'null') THEN
            RAISE EXCEPTION 'source fragment locator cannot be empty';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER source_fragments_require_locator
        BEFORE INSERT OR UPDATE ON source_fragments
        FOR EACH ROW EXECUTE FUNCTION noemosyne_check_fragment_locator();

        CREATE OR REPLACE FUNCTION noemosyne_check_review_separation()
        RETURNS trigger AS $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM proposal_items i JOIN proposals p ON p.id = i.proposal_id
            WHERE i.id = NEW.proposal_item_id AND p.proposer_actor_id = NEW.reviewer_actor_id
          ) THEN
            RAISE EXCEPTION 'a proposer cannot review their own proposal';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER review_decisions_separate_duty
        BEFORE INSERT ON review_decisions
        FOR EACH ROW EXECUTE FUNCTION noemosyne_check_review_separation();

        CREATE OR REPLACE FUNCTION noemosyne_proposal_content_immutable()
        RETURNS trigger AS $$
        BEGIN
          IF OLD.status <> 'draft' AND (
            NEW.namespace_id IS DISTINCT FROM OLD.namespace_id OR
            NEW.proposer_actor_id IS DISTINCT FROM OLD.proposer_actor_id OR
            NEW.title IS DISTINCT FROM OLD.title OR
            NEW.description IS DISTINCT FROM OLD.description OR
            NEW.base_revision_token IS DISTINCT FROM OLD.base_revision_token
          ) THEN
            RAISE EXCEPTION 'submitted proposal content is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER proposals_immutable_after_submission
        BEFORE UPDATE ON proposals
        FOR EACH ROW EXECUTE FUNCTION noemosyne_proposal_content_immutable();

        CREATE OR REPLACE FUNCTION noemosyne_proposal_item_content_immutable()
        RETURNS trigger AS $$
        DECLARE parent_status text;
        BEGIN
          SELECT status INTO parent_status FROM proposals WHERE id = OLD.proposal_id;
          IF TG_OP = 'DELETE' THEN
            IF parent_status <> 'draft' THEN
              RAISE EXCEPTION 'submitted proposal items are immutable';
            END IF;
            RETURN OLD;
          END IF;
          IF parent_status <> 'draft' AND (
            NEW.proposal_id IS DISTINCT FROM OLD.proposal_id OR
            NEW.position IS DISTINCT FROM OLD.position OR
            NEW.command_type IS DISTINCT FROM OLD.command_type OR
            NEW.payload_json::text IS DISTINCT FROM OLD.payload_json::text OR
            NEW.preconditions_json::text IS DISTINCT FROM OLD.preconditions_json::text
          ) THEN
            RAISE EXCEPTION 'submitted proposal items are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER proposal_items_immutable_after_submission
        BEFORE UPDATE OR DELETE ON proposal_items
        FOR EACH ROW EXECUTE FUNCTION noemosyne_proposal_item_content_immutable();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "No automated destructive downgrade: restore a backup into a fresh schema "
        "per docs/operations.md"
    )
