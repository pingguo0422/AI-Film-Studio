"""Bind approved director decisions to one-time executable action snapshots.

Revision ID: d9a4f2c8b710
Revises: c7d4e9a12f60
"""
from alembic import op
import sqlalchemy as sa

revision = "d9a4f2c8b710"
down_revision = "c7d4e9a12f60"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("director_decision_cases") as batch:
        batch.add_column(sa.Column("authorized_action_snapshot", sa.JSON(), nullable=True))
    op.create_table(
        "action_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("decision_case_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("action_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('succeeded')", name="action_execution_status_valid"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_case_id"], ["director_decision_cases.id"], ondelete="RESTRICT", name="fk_action_executions_decision_case"),
        sa.ForeignKeyConstraint(["requested_by"], ["principals.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_action_executions_project_idempotency"),
        sa.UniqueConstraint("decision_case_id", name="uq_action_executions_decision_case"),
    )
    op.create_index("ix_action_executions_project_created", "action_executions", ["project_id", "created_at"])


def downgrade():
    op.drop_index("ix_action_executions_project_created", table_name="action_executions")
    op.drop_table("action_executions")
    with op.batch_alter_table("director_decision_cases") as batch:
        batch.drop_column("authorized_action_snapshot")
