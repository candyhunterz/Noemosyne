"""Require accepted canonical rows to have accepted process provenance.

Revision ID: 0004_process_provenance
Revises: 0003_assessment_chains
"""

from alembic import op

revision = "0004_process_provenance"
down_revision = "0003_assessment_chains"
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
    """Install deferred process-provenance validation for accepted rows."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION noemosyne_canonical_namespace(
          canonical_table text,
          canonical_row jsonb
        ) RETURNS text AS $$
        DECLARE
          canonical_namespace text;
          challenge_type text;
        BEGIN
          IF canonical_table IN (
            'entities', 'claims', 'source_artifacts', 'arguments', 'evidence_items',
            'evidence_dependency_groups', 'assessment_policies', 'questions'
          ) THEN
            RETURN canonical_row->>'namespace_id';
          ELSIF canonical_table = 'entity_aliases' THEN
            SELECT namespace_id INTO canonical_namespace FROM entities
             WHERE id = canonical_row->>'entity_id';
          ELSIF canonical_table IN (
            'claim_versions', 'claim_entities', 'assertions', 'epistemic_assessments',
            'revision_events'
          ) THEN
            SELECT namespace_id INTO canonical_namespace FROM claims
             WHERE id = canonical_row->>'claim_id';
          ELSIF canonical_table = 'source_fragments' THEN
            SELECT namespace_id INTO canonical_namespace FROM source_artifacts
             WHERE id = canonical_row->>'source_artifact_id';
          ELSIF canonical_table = 'argument_premises' THEN
            SELECT namespace_id INTO canonical_namespace FROM arguments
             WHERE id = canonical_row->>'argument_id';
          ELSIF canonical_table = 'evidence_item_sources' THEN
            SELECT namespace_id INTO canonical_namespace FROM evidence_items
             WHERE id = canonical_row->>'evidence_item_id';
          ELSIF canonical_table = 'evidence_dependency_members' THEN
            SELECT namespace_id INTO canonical_namespace FROM evidence_dependency_groups
             WHERE id = canonical_row->>'dependency_group_id';
          ELSIF canonical_table = 'evidence_links' THEN
            SELECT namespace_id INTO canonical_namespace FROM claims
             WHERE id = canonical_row->>'claim_id';
          ELSIF canonical_table = 'claim_relations' THEN
            SELECT namespace_id INTO canonical_namespace FROM claims
             WHERE id = canonical_row->>'source_claim_id';
          ELSIF canonical_table = 'assessment_inputs' THEN
            SELECT claim.namespace_id INTO canonical_namespace
              FROM epistemic_assessments assessment
              JOIN claims claim ON claim.id = assessment.claim_id
             WHERE assessment.id = canonical_row->>'assessment_id';
          ELSIF canonical_table = 'revision_impacts' THEN
            SELECT claim.namespace_id INTO canonical_namespace
              FROM revision_events revision
              JOIN claims claim ON claim.id = revision.claim_id
             WHERE revision.id = canonical_row->>'revision_event_id';
          ELSIF canonical_table = 'question_claims' THEN
            SELECT namespace_id INTO canonical_namespace FROM questions
             WHERE id = canonical_row->>'question_id';
          ELSIF canonical_table = 'challenges' THEN
            challenge_type := canonical_row->>'target_type';
            CASE challenge_type
              WHEN 'claim' THEN
                SELECT namespace_id INTO canonical_namespace FROM claims
                 WHERE id = canonical_row->>'target_id';
              WHEN 'source_artifact' THEN
                SELECT namespace_id INTO canonical_namespace FROM source_artifacts
                 WHERE id = canonical_row->>'target_id';
              WHEN 'source_fragment' THEN
                SELECT source.namespace_id INTO canonical_namespace
                  FROM source_fragments fragment
                  JOIN source_artifacts source ON source.id = fragment.source_artifact_id
                 WHERE fragment.id = canonical_row->>'target_id';
              WHEN 'evidence_item' THEN
                SELECT namespace_id INTO canonical_namespace FROM evidence_items
                 WHERE id = canonical_row->>'target_id';
              WHEN 'evidence_link' THEN
                SELECT claim.namespace_id INTO canonical_namespace
                  FROM evidence_links link
                  JOIN claims claim ON claim.id = link.claim_id
                 WHERE link.id = canonical_row->>'target_id';
              WHEN 'argument' THEN
                SELECT namespace_id INTO canonical_namespace FROM arguments
                 WHERE id = canonical_row->>'target_id';
              WHEN 'assessment' THEN
                SELECT claim.namespace_id INTO canonical_namespace
                  FROM epistemic_assessments assessment
                  JOIN claims claim ON claim.id = assessment.claim_id
                 WHERE assessment.id = canonical_row->>'target_id';
              WHEN 'claim_relation' THEN
                SELECT claim.namespace_id INTO canonical_namespace
                  FROM claim_relations relation
                  JOIN claims claim ON claim.id = relation.source_claim_id
                 WHERE relation.id = canonical_row->>'target_id';
              WHEN 'question' THEN
                SELECT namespace_id INTO canonical_namespace FROM questions
                 WHERE id = canonical_row->>'target_id';
              ELSE
                canonical_namespace := NULL;
            END CASE;
            IF canonical_namespace IS DISTINCT FROM canonical_row->>'namespace_id' THEN
              RETURN NULL;
            END IF;
          END IF;
          RETURN canonical_namespace;
        END;
        $$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

        CREATE OR REPLACE FUNCTION noemosyne_validate_canonical_provenance(
          canonical_table text,
          canonical_row jsonb
        ) RETURNS void AS $$
        DECLARE
          provenance_item_id text;
          canonical_namespace text;
          proposal_namespace text;
          proposal_proposer text;
          proposal_status text;
          item_status text;
        BEGIN
          IF canonical_row->>'status' IS DISTINCT FROM 'accepted' THEN
            RETURN;
          END IF;
          provenance_item_id := canonical_row->>'proposal_item_id';
          IF provenance_item_id IS NULL OR length(trim(provenance_item_id)) = 0 THEN
            RAISE EXCEPTION 'accepted canonical row requires proposal item provenance';
          END IF;
          SELECT proposal.namespace_id, proposal.proposer_actor_id, proposal.status, item.status
            INTO proposal_namespace, proposal_proposer, proposal_status, item_status
            FROM proposal_items item
            JOIN proposals proposal ON proposal.id = item.proposal_id
           WHERE item.id = provenance_item_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'accepted canonical row references a missing proposal item';
          END IF;
          IF item_status <> 'accepted' THEN
            RAISE EXCEPTION 'accepted canonical row requires an accepted proposal item';
          END IF;
          IF proposal_status NOT IN ('accepted', 'partially_accepted') THEN
            RAISE EXCEPTION 'accepted canonical row requires a terminal accepted proposal';
          END IF;
          canonical_namespace := noemosyne_canonical_namespace(
            canonical_table, canonical_row
          );
          IF canonical_namespace IS NULL
             OR canonical_namespace IS DISTINCT FROM proposal_namespace THEN
            RAISE EXCEPTION 'accepted canonical row provenance namespace mismatch';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM actors proposer
             WHERE proposer.id = proposal_proposer
               AND proposer.namespace_id = proposal_namespace
          ) THEN
            RAISE EXCEPTION 'accepted canonical row has invalid proposer provenance';
          END IF;
          IF NOT EXISTS (
            SELECT 1
              FROM review_decisions review
              JOIN actors reviewer ON reviewer.id = review.reviewer_actor_id
             WHERE review.proposal_item_id = provenance_item_id
               AND review.decision = 'accept'
               AND review.reviewer_actor_id <> proposal_proposer
               AND reviewer.namespace_id = proposal_namespace
          ) OR EXISTS (
            SELECT 1 FROM review_decisions review
             WHERE review.proposal_item_id = provenance_item_id
               AND review.decision IN ('reject', 'request_changes')
          ) OR EXISTS (
            SELECT 1
              FROM review_decisions review
              LEFT JOIN actors reviewer ON reviewer.id = review.reviewer_actor_id
             WHERE review.proposal_item_id = provenance_item_id
               AND (
                 review.reviewer_actor_id = proposal_proposer
                 OR reviewer.namespace_id IS DISTINCT FROM proposal_namespace
               )
          ) THEN
            RAISE EXCEPTION
              'accepted canonical row requires an effective separated accepted review';
          END IF;
        END;
        $$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

        CREATE OR REPLACE FUNCTION noemosyne_check_canonical_provenance()
        RETURNS trigger AS $$
        BEGIN
          PERFORM noemosyne_validate_canonical_provenance(TG_TABLE_NAME, to_jsonb(NEW));
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
        """
    )
    for table in CANONICAL_TABLES:
        constraint = f"{table}_proposal_item_id_fkey"
        trigger = f"{table}_process_provenance"
        op.execute(
            f"""
            ALTER TABLE {table} ALTER CONSTRAINT {constraint}
              DEFERRABLE INITIALLY DEFERRED;
            CREATE CONSTRAINT TRIGGER {trigger}
              AFTER INSERT OR UPDATE ON {table}
              DEFERRABLE INITIALLY DEFERRED
              FOR EACH ROW EXECUTE FUNCTION noemosyne_check_canonical_provenance();
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
