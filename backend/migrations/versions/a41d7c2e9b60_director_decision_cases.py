"""Persist Executive Director recommendations and human decisions.

Revision ID: a41d7c2e9b60
Revises: 9c6e2a41b7d0
"""
from alembic import op
import sqlalchemy as sa

revision = "a41d7c2e9b60"
down_revision = "9c6e2a41b7d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "director_decision_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.String(length=64), nullable=False),
        sa.Column("source_brief_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_state_digest", sa.String(length=64), nullable=False),
        sa.Column("recommendation_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("approval_required", sa.String(length=24), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("proposal_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open', 'approved', 'rejected', 'deferred', 'closed')", name="director_decision_case_status_valid"),
        sa.CheckConstraint("decision IS NULL OR decision IN ('approved', 'rejected', 'deferred', 'closed')", name="director_decision_case_decision_valid"),
        sa.CheckConstraint("(status = 'open' AND decision IS NULL AND decided_by IS NULL AND decided_at IS NULL) OR (status <> 'open' AND decision = status AND decided_by IS NOT NULL AND decided_at IS NOT NULL)", name="director_decision_case_decision_consistent"),
        sa.CheckConstraint("severity IN ('critical', 'high', 'medium', 'low', 'info')", name="director_decision_case_severity_valid"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "case_key", name="uq_director_decision_cases_project_key"),
    )
    op.create_index("ix_director_decision_cases_project_status", "director_decision_cases", ["project_id", "status", "created_at"])
    with op.batch_alter_table("director_decision_cases") as batch:
        batch.alter_column("status", server_default=None)

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("""CREATE OR REPLACE FUNCTION afs_guard_director_decision_case() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'director decision cases are retained for audit'; END IF;
          IF OLD.status <> 'open' THEN RAISE EXCEPTION 'director decision case disposition is one-time'; END IF;
          IF (NEW.project_id, NEW.case_key, NEW.source_brief_sha256, NEW.source_state_digest,
              NEW.recommendation_code, NEW.severity, NEW.approval_required, NEW.created_at)
             IS DISTINCT FROM
             (OLD.project_id, OLD.case_key, OLD.source_brief_sha256, OLD.source_state_digest,
              OLD.recommendation_code, OLD.severity, OLD.approval_required, OLD.created_at)
             OR to_jsonb(NEW.evidence_refs) IS DISTINCT FROM to_jsonb(OLD.evidence_refs)
             OR to_jsonb(NEW.proposal_snapshot) IS DISTINCT FROM to_jsonb(OLD.proposal_snapshot)
          THEN RAISE EXCEPTION 'director decision case proposal snapshot is immutable'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER trg_director_decision_case_immutable BEFORE UPDATE OR DELETE ON director_decision_cases FOR EACH ROW EXECUTE FUNCTION afs_guard_director_decision_case()")
    elif dialect == "sqlite":
        op.execute("""CREATE TRIGGER trg_director_decision_case_immutable BEFORE UPDATE ON director_decision_cases
        WHEN OLD.status <> 'open' OR NEW.project_id IS NOT OLD.project_id OR NEW.case_key IS NOT OLD.case_key
          OR NEW.source_brief_sha256 IS NOT OLD.source_brief_sha256
          OR NEW.source_state_digest IS NOT OLD.source_state_digest
          OR NEW.recommendation_code IS NOT OLD.recommendation_code
          OR NEW.severity IS NOT OLD.severity OR NEW.approval_required IS NOT OLD.approval_required
          OR NEW.evidence_refs IS NOT OLD.evidence_refs OR NEW.proposal_snapshot IS NOT OLD.proposal_snapshot
          OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'director decision case proposal snapshot is immutable'); END""")
        op.execute("CREATE TRIGGER trg_director_decision_case_no_delete BEFORE DELETE ON director_decision_cases BEGIN SELECT RAISE(ABORT, 'director decision cases are retained for audit'); END")


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_director_decision_case_immutable ON director_decision_cases")
        op.execute("DROP FUNCTION IF EXISTS afs_guard_director_decision_case()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_director_decision_case_immutable")
        op.execute("DROP TRIGGER IF EXISTS trg_director_decision_case_no_delete")
    op.drop_index("ix_director_decision_cases_project_status", table_name="director_decision_cases")
    op.drop_table("director_decision_cases")
