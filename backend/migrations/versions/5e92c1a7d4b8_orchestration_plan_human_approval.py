"""Require explicit human approval before orchestration plan materialization.

Revision ID: 5e92c1a7d4b8
Revises: 2c84a1d9e650
"""
from alembic import op
import sqlalchemy as sa

revision = "5e92c1a7d4b8"
down_revision = "2c84a1d9e650"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orchestration_plans") as batch:
        batch.add_column(sa.Column("approval_status", sa.String(length=24), nullable=False, server_default="pending"))
        batch.add_column(sa.Column("approved_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("approval_decided_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("approval_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("plan_sha256", sa.String(length=64), nullable=False, server_default=""))
        batch.create_check_constraint(
            "ck_orchestration_plan_approval_status",
            "approval_status IN ('pending', 'approved', 'rejected')",
        )
        batch.alter_column("approval_status", server_default=None)
        batch.alter_column("plan_sha256", server_default=None)


def downgrade():
    with op.batch_alter_table("orchestration_plans") as batch:
        batch.drop_constraint("ck_orchestration_plan_approval_status", type_="check")
        for name in ["plan_sha256", "approval_note", "approval_decided_at", "approved_by", "approval_status"]:
            batch.drop_column(name)
