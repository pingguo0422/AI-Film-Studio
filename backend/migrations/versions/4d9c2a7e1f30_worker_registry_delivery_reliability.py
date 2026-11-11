"""Worker registry, durable outbox claims/retries and task dead letters.

Revision ID: 4d9c2a7e1f30
Revises: 13a9c2e4f601
"""
from alembic import op
import sqlalchemy as sa

revision = "4d9c2a7e1f30"
down_revision = "13a9c2e4f601"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("outbox_events") as batch:
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("claimed_by", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("claim_token", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error", sa.JSON(), nullable=True))
        batch.create_check_constraint("outbox_attempt_bounds", "attempt_count >= 0 AND max_attempts > 0")
        batch.create_check_constraint("outbox_status_valid", "status IN ('pending', 'publishing', 'published', 'dead')")

    op.create_table(
        "worker_instances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("host_name", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("metadata_snapshot", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('starting', 'online', 'stopping', 'offline', 'stale')", name="worker_instance_status_valid"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id", name="uq_worker_instances_worker_id"),
    )
    op.create_index("ix_worker_instances_status_heartbeat", "worker_instances", ["status", "last_heartbeat_at"])

    op.create_table(
        "task_dead_letters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("error_detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id", "task_id"], ["tasks.project_id", "tasks.id"], name="fk_task_dead_letters_task", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_task_dead_letters_task"),
    )
    op.create_index("ix_task_dead_letters_created", "task_dead_letters", ["created_at"])


def downgrade():
    op.drop_index("ix_task_dead_letters_created", table_name="task_dead_letters")
    op.drop_table("task_dead_letters")
    op.drop_index("ix_worker_instances_status_heartbeat", table_name="worker_instances")
    op.drop_table("worker_instances")
    with op.batch_alter_table("outbox_events") as batch:
        batch.drop_constraint("outbox_status_valid", type_="check")
        batch.drop_constraint("outbox_attempt_bounds", type_="check")
        for column in ["last_error", "claim_expires_at", "claim_token", "claimed_by", "next_attempt_at", "max_attempts"]:
            batch.drop_column(column)
