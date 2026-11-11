"""Agent runtime task leases, retries, cancellation and idempotent creation.

Revision ID: 13a9c2e4f601
Revises: 8c58a10612ac
"""
from alembic import op
import sqlalchemy as sa

revision = "13a9c2e4f601"
down_revision = "8c58a10612ac"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("output_snapshot", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("lease_owner", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("error_detail", sa.JSON(), nullable=True))
        batch.create_unique_constraint("uq_tasks_project_idempotency", ["project_id", "idempotency_key"])
        batch.create_check_constraint("task_attempt_bounds", "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts")
        batch.create_check_constraint("task_status_valid", "status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled')")

def downgrade():
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("task_status_valid", type_="check")
        batch.drop_constraint("task_attempt_bounds", type_="check")
        batch.drop_constraint("uq_tasks_project_idempotency", type_="unique")
        for name in ["error_detail", "finished_at", "started_at", "cancel_requested", "retry_after", "lease_expires_at", "lease_token", "lease_owner", "max_attempts", "attempt_count", "idempotency_key", "output_snapshot"]:
            batch.drop_column(name)
