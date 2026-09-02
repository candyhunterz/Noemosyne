"""Finalize assessment supersession and revision-chain constraints.

Revision ID: 0003_assessment_revision_chains
Revises: 0002_audit_integrity
"""

from alembic import op

revision = "0003_assessment_chains"
down_revision = "0002_audit_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install the chain checks idempotently for already-upgraded databases."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_check_assessment_supersession()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'accepted' AND NEW.supersedes_id IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM epistemic_assessments previous
                WHERE previous.id = NEW.supersedes_id
                  AND previous.claim_id = NEW.claim_id
                  AND previous.status = 'accepted'
             ) THEN
            RAISE EXCEPTION 'assessment supersession is not accepted on the same claim';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS assessments_require_valid_supersession
          ON epistemic_assessments;
        CREATE CONSTRAINT TRIGGER assessments_require_valid_supersession
          AFTER INSERT OR UPDATE ON epistemic_assessments
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION noemosyne_check_assessment_supersession();

        CREATE OR REPLACE FUNCTION noemosyne_check_revision_chain()
        RETURNS trigger AS $$
        DECLARE
          revision_namespace text;
        BEGIN
          IF NEW.status <> 'accepted' THEN
            RETURN NEW;
          END IF;
          SELECT namespace_id INTO revision_namespace FROM claims
           WHERE id = NEW.claim_id AND status = 'accepted';
          IF revision_namespace IS NULL
             OR NOT EXISTS (
               SELECT 1 FROM epistemic_assessments after_assessment
                WHERE after_assessment.id = NEW.after_assessment_id
                  AND after_assessment.claim_id = NEW.claim_id
                  AND after_assessment.status = 'accepted'
                  AND COALESCE(after_assessment.supersedes_id, '') =
                      COALESCE(NEW.before_assessment_id, '')
             )
             OR (NEW.before_assessment_id IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM epistemic_assessments before_assessment
                WHERE before_assessment.id = NEW.before_assessment_id
                  AND before_assessment.claim_id = NEW.claim_id
                  AND before_assessment.status = 'accepted'
             ))
             OR NOT EXISTS (
               SELECT 1 FROM actors author
                WHERE author.id = NEW.author_actor_id
                  AND author.namespace_id = revision_namespace
             )
             OR NOT EXISTS (
               SELECT 1 FROM actors reviewer
                WHERE reviewer.id = NEW.reviewer_actor_id
                  AND reviewer.namespace_id = revision_namespace
             ) THEN
            RAISE EXCEPTION 'revision event must preserve same-namespace assessment provenance';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS revision_events_require_chain ON revision_events;
        CREATE CONSTRAINT TRIGGER revision_events_require_chain
          AFTER INSERT OR UPDATE ON revision_events
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION noemosyne_check_revision_chain();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "No automated destructive downgrade: restore a backup into a fresh schema "
        "per docs/operations.md"
    )
