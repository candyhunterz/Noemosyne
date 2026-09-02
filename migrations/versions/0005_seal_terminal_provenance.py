"""Seal terminal proposal provenance against later workflow mutation.

Revision ID: 0005_seal_terminal_provenance
Revises: 0004_process_provenance
"""

from alembic import op

revision = "0005_seal_terminal_provenance"
down_revision = "0004_process_provenance"
branch_labels = None
depends_on = None


CANONICAL_TABLES = (
    "entities",
    "entity_aliases",
    "claims",
    "claim_versions",
    "claim_entities",
    "source_artifacts",
    "source_fragments",
    "assertions",
    "arguments",
    "argument_premises",
    "evidence_items",
    "evidence_item_sources",
    "evidence_dependency_groups",
    "evidence_dependency_members",
    "assessment_policies",
    "evidence_links",
    "challenges",
    "claim_relations",
    "epistemic_assessments",
    "assessment_inputs",
    "revision_events",
    "revision_impacts",
    "questions",
    "question_claims",
)


def upgrade() -> None:
    """Lock terminal workflow provenance and serialize review admission."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_seal_terminal_proposal()
        RETURNS trigger AS $$
        BEGIN
          IF OLD.status IN ('accepted', 'partially_accepted', 'rejected', 'stale') THEN
            RAISE EXCEPTION 'terminal proposals are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          IF NEW.status IN ('accepted', 'partially_accepted', 'rejected', 'stale')
             AND OLD.status <> 'in_review' THEN
            RAISE EXCEPTION 'proposals may become terminal only from in_review';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

        CREATE TRIGGER proposals_seal_terminal
          BEFORE UPDATE OR DELETE ON proposals
          FOR EACH ROW EXECUTE FUNCTION noemosyne_seal_terminal_proposal();

        CREATE OR REPLACE FUNCTION noemosyne_seal_terminal_proposal_item()
        RETURNS trigger AS $$
        DECLARE
          parent_status text;
        BEGIN
          SELECT proposal.status
            INTO parent_status
            FROM proposals proposal
           WHERE proposal.id = OLD.proposal_id
           FOR UPDATE;
          IF parent_status IN ('accepted', 'partially_accepted', 'rejected', 'stale') THEN
            RAISE EXCEPTION 'proposal items under terminal proposals are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

        CREATE TRIGGER proposal_items_seal_terminal
          BEFORE UPDATE OR DELETE ON proposal_items
          FOR EACH ROW EXECUTE FUNCTION noemosyne_seal_terminal_proposal_item();

        CREATE OR REPLACE FUNCTION noemosyne_check_review_separation()
        RETURNS trigger AS $$
        DECLARE
          proposal_namespace text;
          proposer text;
          proposal_status text;
          reviewer_namespace text;
        BEGIN
          SELECT proposal.namespace_id, proposal.proposer_actor_id, proposal.status
            INTO proposal_namespace, proposer, proposal_status
            FROM proposal_items item
            JOIN proposals proposal ON proposal.id = item.proposal_id
           WHERE item.id = NEW.proposal_item_id
           FOR UPDATE OF proposal;
          SELECT namespace_id INTO reviewer_namespace FROM actors
           WHERE id = NEW.reviewer_actor_id;
          IF proposal_namespace IS NULL THEN
            RAISE EXCEPTION 'review proposal item does not exist';
          END IF;
          IF proposal_status <> 'in_review' THEN
            RAISE EXCEPTION 'reviews may only be recorded while proposal is in_review';
          END IF;
          IF proposer = NEW.reviewer_actor_id THEN
            RAISE EXCEPTION 'a proposer cannot review their own proposal';
          END IF;
          IF reviewer_namespace IS DISTINCT FROM proposal_namespace THEN
            RAISE EXCEPTION 'reviewer must belong to the proposal namespace';
          END IF;
          IF length(trim(NEW.rationale)) = 0 THEN
            RAISE EXCEPTION 'review rationale is required';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
        """
    )
    for table in CANONICAL_TABLES:
        op.execute(
            f"""
            SELECT noemosyne_validate_canonical_provenance('{table}', to_jsonb(row_value))
              FROM {table} AS row_value
             WHERE row_value.status = 'accepted';
            """
        )


def downgrade() -> None:
    raise RuntimeError(
        "No automated destructive downgrade: restore a backup into a fresh schema "
        "per docs/operations.md"
    )
