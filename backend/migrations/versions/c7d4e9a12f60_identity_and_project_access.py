"""Add principals, opaque API tokens and identity persistence.

Revision ID: c7d4e9a12f60
Revises: a41d7c2e9b60
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d4e9a12f60"
down_revision = "a41d7c2e9b60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "principals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_kind", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("principal_kind IN ('human', 'service')", name="principal_kind_valid"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_principals_kind_active", "principals", ["principal_kind", "is_active"])

    # Preserve identities already referenced by project membership records.
    op.execute("""INSERT INTO principals (id, principal_kind, display_name, is_active, created_at)
        SELECT DISTINCT pm.principal_id, 'human', 'Legacy principal', TRUE, CURRENT_TIMESTAMP
        FROM project_members AS pm
        WHERE NOT EXISTS (SELECT 1 FROM principals p WHERE p.id = pm.principal_id)""")
    with op.batch_alter_table("project_members") as batch:
        batch.create_foreign_key(
            "fk_project_members_principal", "principals", ["principal_id"], ["id"], ondelete="RESTRICT"
        )

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("token_prefix", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(token_hash) = 64", name="api_token_hash_length"),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_prefix"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_api_tokens_principal_active", "api_tokens", ["principal_id", "revoked_at", "expires_at"])
    with op.batch_alter_table("principals") as batch:
        batch.alter_column("is_active", server_default=None)
        batch.alter_column("created_at", server_default=None)
    with op.batch_alter_table("api_tokens") as batch:
        batch.alter_column("created_at", server_default=None)


def downgrade():
    with op.batch_alter_table("project_members") as batch:
        batch.drop_constraint("fk_project_members_principal", type_="foreignkey")
    op.drop_index("ix_api_tokens_principal_active", table_name="api_tokens")
    op.drop_table("api_tokens")
    op.drop_index("ix_principals_kind_active", table_name="principals")
    op.drop_table("principals")
