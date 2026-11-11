"""Fence stale worker process generations and support concurrent inbox inserts.

Revision ID: 7f31b6c2a904
Revises: 4d9c2a7e1f30
"""
from alembic import op
import sqlalchemy as sa

revision = "7f31b6c2a904"
down_revision = "4d9c2a7e1f30"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("worker_instances") as batch:
        batch.add_column(sa.Column("instance_token", sa.String(length=36), nullable=False, server_default="legacy"))
        batch.alter_column("instance_token", server_default=None)


def downgrade():
    with op.batch_alter_table("worker_instances") as batch:
        batch.drop_column("instance_token")
