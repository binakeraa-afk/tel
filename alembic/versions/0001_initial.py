"""Schéma initial : videos, system_state, post_logs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("tg_file_unique_id", sa.String(length=128), nullable=False),
        sa.Column("tg_file_id", sa.String(length=256), nullable=False),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column("source_channel", sa.String(length=255), nullable=True),
        sa.Column("original_caption", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("queue_seq", sa.BigInteger(), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("x_tweet_id", sa.String(length=64), nullable=True),
        sa.Column("x_media_id", sa.String(length=64), nullable=True),
        sa.Column("published_caption", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("tg_file_unique_id", name="uq_videos_file_unique_id"),
    )
    op.create_index("ix_videos_file_unique_id", "videos", ["tg_file_unique_id"])
    op.create_index("ix_videos_status", "videos", ["status"])
    op.create_index("ix_videos_queue_seq", "videos", ["queue_seq"])
    op.create_index("ix_videos_sha256", "videos", ["sha256"])

    op.create_table(
        "system_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("next_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("total_published", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queue_counter", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("x_cookies_json", sa.Text(), nullable=True),
    )

    op.create_table(
        "post_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tweet_id", sa.String(length=64), nullable=True),
        sa.Column("attempt", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_post_logs_video_id", "post_logs", ["video_id"])


def downgrade() -> None:
    op.drop_table("post_logs")
    op.drop_table("system_state")
    op.drop_index("ix_videos_sha256", table_name="videos")
    op.drop_index("ix_videos_queue_seq", table_name="videos")
    op.drop_index("ix_videos_status", table_name="videos")
    op.drop_index("ix_videos_file_unique_id", table_name="videos")
    op.drop_table("videos")
