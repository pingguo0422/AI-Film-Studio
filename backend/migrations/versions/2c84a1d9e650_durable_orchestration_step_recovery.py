"""Persist orchestration step identity, task linkage and execution outcomes.

Revision ID: 2c84a1d9e650
Revises: 7f31b6c2a904
"""
from alembic import op
import sqlalchemy as sa

revision = "2c84a1d9e650"
down_revision = "7f31b6c2a904"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orchestration_plan_steps") as batch:
        batch.add_column(sa.Column("step_key", sa.String(length=96), nullable=True))
        batch.add_column(sa.Column("task_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("depends_on_step_keys", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("output_snapshot", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("error_detail", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint("uq_orchestration_plan_step_task", ["task_id"])
        batch.create_foreign_key("fk_orchestration_plan_step_task", "tasks", ["task_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_orchestration_plan_steps_plan_key", "orchestration_plan_steps", ["plan_id", "step_key"], unique=True)


def downgrade():
    op.drop_index("ix_orchestration_plan_steps_plan_key", table_name="orchestration_plan_steps")
    with op.batch_alter_table("orchestration_plan_steps") as batch:
        batch.drop_constraint("fk_orchestration_plan_step_task", type_="foreignkey")
        batch.drop_constraint("uq_orchestration_plan_step_task", type_="unique")
        for name in ["finished_at", "started_at", "error_detail", "output_snapshot", "depends_on_step_keys", "task_id", "step_key"]:
            batch.drop_column(name)
