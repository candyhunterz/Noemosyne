"""Enforce proposal namespace, provenance, and append-only integrity.

Revision ID: 0002_audit_integrity
Revises: 0001_milestone_1
"""

from __future__ import annotations

from alembic import op

revision = "0002_audit_integrity"
down_revision = "0001_milestone_1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE source_artifacts
          ADD CONSTRAINT ck_source_artifacts_complete_metadata CHECK (
            length(trim(title)) > 0 AND
            length(trim(canonical_uri)) > 0 AND
            length(trim(license_basis)) > 0
          );
        ALTER TABLE source_fragments
          ADD CONSTRAINT ck_source_fragments_license CHECK (
            length(trim(license_basis)) > 0
          );
        ALTER TABLE evidence_items
          ADD CONSTRAINT ck_evidence_items_content_kind CHECK (
            (kind = 'source_fragment' AND argument_id IS NULL) OR
            (kind = 'argument' AND argument_id IS NOT NULL)
          );
        ALTER TABLE claim_versions
          ADD CONSTRAINT fk_claim_versions_supersedes
          FOREIGN KEY (supersedes_id) REFERENCES claim_versions(id)
          DEFERRABLE INITIALLY DEFERRED;
        ALTER TABLE claim_versions
          ADD CONSTRAINT ck_claim_versions_not_self_superseding CHECK (
            supersedes_id IS NULL OR supersedes_id <> id
          );
        ALTER TABLE epistemic_assessments
          ADD CONSTRAINT fk_assessments_supersedes
          FOREIGN KEY (supersedes_id) REFERENCES epistemic_assessments(id)
          DEFERRABLE INITIALLY DEFERRED;
        ALTER TABLE epistemic_assessments
          ADD CONSTRAINT ck_assessments_not_self_superseding CHECK (
            supersedes_id IS NULL OR supersedes_id <> id
          );
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'noemosyne_projection_owner') THEN
            CREATE ROLE noemosyne_projection_owner NOLOGIN;
          END IF;
        END
        $$;
        ALTER ROLE noemosyne_projection_owner
          NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

        CREATE OR REPLACE FUNCTION noemosyne_reject_accepted_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status = 'accepted' THEN
              RAISE EXCEPTION 'accepted ledger rows are append-only; supersede instead';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status = 'accepted' THEN
            IF TG_TABLE_NAME = 'claims' THEN
              IF current_user = 'noemosyne_projection_owner'
                 AND NEW.id IS NOT DISTINCT FROM OLD.id
                 AND NEW.namespace_id IS NOT DISTINCT FROM OLD.namespace_id
                 AND NEW.status IS NOT DISTINCT FROM OLD.status
                 AND NEW.supersedes_id IS NOT DISTINCT FROM OLD.supersedes_id
                 AND NEW.proposal_item_id IS NOT DISTINCT FROM OLD.proposal_item_id
                 AND NEW.recorded_at IS NOT DISTINCT FROM OLD.recorded_at
                 AND NEW.claim_form IS NOT DISTINCT FROM OLD.claim_form
                 AND NEW.normalization_status IS NOT DISTINCT FROM OLD.normalization_status
                 AND NEW.current_version_id IS DISTINCT FROM OLD.current_version_id THEN
                RETURN NEW;
              END IF;
            END IF;
            RAISE EXCEPTION 'accepted ledger rows are append-only; supersede instead';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE OR REPLACE FUNCTION noemosyne_advance_claim_version(
          requested_claim_id text,
          requested_version_id text,
          requested_proposal_item_id text
        ) RETURNS void AS $$
        DECLARE
          current_version text;
          claim_namespace text;
          proposal_proposer text;
        BEGIN
          SELECT c.current_version_id, c.namespace_id
            INTO current_version, claim_namespace
            FROM claims c
           WHERE c.id = requested_claim_id AND c.status = 'accepted'
           FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'claim projection target is not accepted';
          END IF;
          IF NOT EXISTS (
            SELECT 1
              FROM claim_versions v
             WHERE v.id = requested_version_id
               AND v.claim_id = requested_claim_id
               AND v.status = 'accepted'
               AND v.proposal_item_id = requested_proposal_item_id
               AND v.supersedes_id IS NOT DISTINCT FROM current_version
          ) THEN
            RAISE EXCEPTION 'claim version does not form an authorized supersession';
          END IF;
          SELECT p.proposer_actor_id
            INTO proposal_proposer
            FROM proposal_items i
            JOIN proposals p ON p.id = i.proposal_id
           WHERE i.id = requested_proposal_item_id
             AND i.command_type = 'AddClaimVersion'
             AND p.status = 'in_review'
             AND p.namespace_id = claim_namespace
             AND i.payload_json->>'claim_id' = requested_claim_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'claim projection lacks an in-review proposal item';
          END IF;
          IF NOT EXISTS (
            SELECT 1
              FROM review_decisions r
              JOIN actors a ON a.id = r.reviewer_actor_id
             WHERE r.proposal_item_id = requested_proposal_item_id
               AND r.decision = 'accept'
               AND r.reviewer_actor_id <> proposal_proposer
               AND a.namespace_id = claim_namespace
          ) OR EXISTS (
            SELECT 1 FROM review_decisions r
             WHERE r.proposal_item_id = requested_proposal_item_id
               AND r.decision IN ('reject', 'request_changes')
          ) THEN
            RAISE EXCEPTION 'claim projection lacks an effective accepted review';
          END IF;
          UPDATE claims
             SET current_version_id = requested_version_id
           WHERE id = requested_claim_id;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER
           SET search_path = pg_catalog, public;
        ALTER FUNCTION noemosyne_advance_claim_version(text, text, text)
          OWNER TO noemosyne_projection_owner;
        GRANT USAGE ON SCHEMA public TO noemosyne_projection_owner;
        GRANT SELECT ON claims, claim_versions, proposals, proposal_items,
          review_decisions, actors TO noemosyne_projection_owner;
        GRANT UPDATE (current_version_id) ON claims TO noemosyne_projection_owner;
        REVOKE ALL ON FUNCTION noemosyne_advance_claim_version(text, text, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION noemosyne_advance_claim_version(text, text, text) TO PUBLIC;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_evidence_item_is_resolvable(
          requested_evidence_item_id text
        ) RETURNS boolean AS $$
        DECLARE
          evidence_kind text;
          evidence_namespace text;
          evidence_argument text;
        BEGIN
          SELECT kind, namespace_id, argument_id
            INTO evidence_kind, evidence_namespace, evidence_argument
            FROM evidence_items
           WHERE id = requested_evidence_item_id AND status = 'accepted';
          IF NOT FOUND THEN
            RETURN false;
          END IF;
          IF evidence_kind = 'argument' THEN
            RETURN evidence_argument IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM evidence_item_sources eis
                 WHERE eis.evidence_item_id = requested_evidence_item_id
                   AND eis.status = 'accepted'
              )
              AND EXISTS (
                SELECT 1 FROM arguments a
                JOIN claims c ON c.id = a.conclusion_claim_id
                JOIN actors author ON author.id = a.author_actor_id
                 WHERE a.id = evidence_argument
                   AND a.namespace_id = evidence_namespace
                   AND a.status = 'accepted'
                   AND c.namespace_id = evidence_namespace
                   AND c.status = 'accepted'
                   AND author.namespace_id = evidence_namespace
                   AND EXISTS (
                     SELECT 1 FROM argument_premises premise
                      WHERE premise.argument_id = a.id
                        AND premise.status = 'accepted'
                   )
              );
          END IF;
          IF evidence_kind = 'source_fragment' THEN
            RETURN evidence_argument IS NULL
              AND EXISTS (
                SELECT 1
                  FROM evidence_item_sources eis
                  JOIN source_fragments f ON f.id = eis.source_fragment_id
                  JOIN source_artifacts s ON s.id = f.source_artifact_id
                 WHERE eis.evidence_item_id = requested_evidence_item_id
                   AND eis.status = 'accepted'
                   AND f.status = 'accepted'
                   AND s.status = 'accepted'
                   AND s.namespace_id = evidence_namespace
                   AND f.locator_json::text NOT IN ('{}', 'null')
                   AND length(trim(f.license_basis)) > 0
                   AND (f.stored_text IS NULL OR f.text_hash IS NOT NULL)
                   AND length(trim(s.title)) > 0
                   AND length(trim(s.canonical_uri)) > 0
                   AND length(trim(s.license_basis)) > 0
              )
              AND NOT EXISTS (
                SELECT 1
                  FROM evidence_item_sources eis
                  JOIN source_fragments f ON f.id = eis.source_fragment_id
                  JOIN source_artifacts s ON s.id = f.source_artifact_id
                 WHERE eis.evidence_item_id = requested_evidence_item_id
                   AND eis.status = 'accepted'
                   AND (
                     f.status <> 'accepted' OR s.status <> 'accepted' OR
                     s.namespace_id <> evidence_namespace OR
                     f.locator_json::text IN ('{}', 'null') OR
                     length(trim(f.license_basis)) = 0 OR
                     (f.stored_text IS NOT NULL AND f.text_hash IS NULL) OR
                     length(trim(s.title)) = 0 OR
                     length(trim(s.canonical_uri)) = 0 OR
                     length(trim(s.license_basis)) = 0
                   )
              );
          END IF;
          RETURN false;
        END;
        $$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

        CREATE OR REPLACE FUNCTION noemosyne_check_evidence_item_provenance()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.status = 'accepted'
             AND NOT noemosyne_evidence_item_is_resolvable(NEW.id) THEN
            RAISE EXCEPTION 'accepted evidence item requires resolvable provenance';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE CONSTRAINT TRIGGER evidence_items_require_provenance
          AFTER INSERT OR UPDATE ON evidence_items
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION noemosyne_check_evidence_item_provenance();

        CREATE OR REPLACE FUNCTION noemosyne_check_evidence_link_provenance()
        RETURNS trigger AS $$
        DECLARE
          claim_namespace text;
          evidence_namespace text;
          evaluator_namespace text;
          policy_namespace text;
        BEGIN
          IF NEW.status <> 'accepted' THEN
            RETURN NEW;
          END IF;
          SELECT namespace_id INTO claim_namespace FROM claims
           WHERE id = NEW.claim_id AND status = 'accepted';
          SELECT namespace_id INTO evidence_namespace FROM evidence_items
           WHERE id = NEW.evidence_item_id AND status = 'accepted';
          SELECT namespace_id INTO evaluator_namespace FROM actors
           WHERE id = NEW.evaluator_actor_id;
          SELECT namespace_id INTO policy_namespace FROM assessment_policies
           WHERE id = NEW.assessment_policy_id AND status = 'accepted';
          IF claim_namespace IS NULL
             OR evidence_namespace IS DISTINCT FROM claim_namespace
             OR evaluator_namespace IS DISTINCT FROM claim_namespace
             OR policy_namespace IS DISTINCT FROM claim_namespace
             OR NOT noemosyne_evidence_item_is_resolvable(NEW.evidence_item_id) THEN
            RAISE EXCEPTION 'accepted evidence link requires same-namespace resolvable provenance';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE CONSTRAINT TRIGGER evidence_links_require_provenance
          AFTER INSERT OR UPDATE ON evidence_links
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION noemosyne_check_evidence_link_provenance();
        """
    )
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
        CREATE CONSTRAINT TRIGGER revision_events_require_chain
          AFTER INSERT OR UPDATE ON revision_events
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION noemosyne_check_revision_chain();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_check_review_separation()
        RETURNS trigger AS $$
        DECLARE
          proposal_namespace text;
          proposer text;
          reviewer_namespace text;
        BEGIN
          SELECT p.namespace_id, p.proposer_actor_id
            INTO proposal_namespace, proposer
            FROM proposal_items i JOIN proposals p ON p.id = i.proposal_id
           WHERE i.id = NEW.proposal_item_id;
          SELECT namespace_id INTO reviewer_namespace FROM actors
           WHERE id = NEW.reviewer_actor_id;
          IF proposal_namespace IS NULL THEN
            RAISE EXCEPTION 'review proposal item does not exist';
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
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "No automated destructive downgrade: restore a backup into a fresh schema "
        "per docs/operations.md"
    )
