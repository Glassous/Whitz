"""add conversation_file_links for persistent library-to-conversation workspace attachments

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_file_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("conversation_id", "file_id", name="uq_conv_file_link"),
    )
    op.create_index(
        "ix_conv_file_links_conv_created",
        "conversation_file_links",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_conv_file_links_file_id",
        "conversation_file_links",
        ["file_id"],
    )
    op.create_index(
        "ix_conv_file_links_user_id",
        "conversation_file_links",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conv_file_links_user_id", table_name="conversation_file_links")
    op.drop_index("ix_conv_file_links_file_id", table_name="conversation_file_links")
    op.drop_index("ix_conv_file_links_conv_created", table_name="conversation_file_links")
    op.drop_table("conversation_file_links")
