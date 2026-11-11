"""Add durable Agent quality evaluations and idempotent collaboration messages.

Revision ID: 9c6e2a41b7d0
Revises: 5e92c1a7d4b8
"""
from alembic import op
import sqlalchemy as sa

revision = "9c6e2a41b7d0"
down_revision = "5e92c1a7d4b8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agent_messages") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=160), nullable=True))
        batch.create_unique_constraint("uq_agent_messages_idempotency", ["project_id", "idempotency_key"])

    op.create_table(
        "agent_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rework_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rubric_snapshot", sa.JSON(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("required_changes", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("rework_task_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="agent_evaluation_score_range"),
        sa.CheckConstraint("decision IN ('accepted', 'rework', 'escalate')", name="agent_evaluation_decision_valid"),
        sa.CheckConstraint("rework_round >= 0", name="agent_evaluation_rework_round_nonnegative"),
        sa.ForeignKeyConstraint(["project_id", "agent_run_id"], ["agent_runs.project_id", "agent_runs.id"], ondelete="RESTRICT", name="fk_agent_evaluations_agent_run"),
        sa.ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT", name="fk_agent_evaluations_task"),
        sa.ForeignKeyConstraint(["reviewer_agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id", "rework_task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT", name="fk_agent_evaluations_rework_task_project"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_agent_evaluations_idempotency"),
        sa.UniqueConstraint("rework_task_id", name="uq_agent_evaluations_rework_task"),
    )
    op.create_index("ix_agent_evaluations_run_created", "agent_evaluations", ["agent_run_id", "created_at"])
    with op.batch_alter_table("agent_evaluations") as batch:
        batch.alter_column("rework_round", server_default=None)


def downgrade():
    op.drop_index("ix_agent_evaluations_run_created", table_name="agent_evaluations")
    op.drop_table("agent_evaluations")
    with op.batch_alter_table("agent_messages") as batch:
        batch.drop_constraint("uq_agent_messages_idempotency", type_="unique")
        batch.drop_column("idempotency_key")
