"""Track signed-out access tokens."""

from alembic import op
import sqlalchemy as sa

revision = "0e3d0d29a91b"
down_revision = "51d17c1d8b0e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "revoked_access_tokens",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_revoked_access_tokens_expires_at", "revoked_access_tokens", ["expires_at"])


def downgrade():
    op.drop_table("revoked_access_tokens")
