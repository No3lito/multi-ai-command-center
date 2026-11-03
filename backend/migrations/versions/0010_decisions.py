"""decisions

Owner decisions raised by decision briefs, each with the follow-up the agents prepared.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03 02:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("room_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("cost", sa.Text(), nullable=True),
        sa.Column("follow_up", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("owner_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=40), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("follow_up_run_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status in ('pending','approved','declined','more_info','dismissed')", name="decision_status"
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["principals.id"]),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("decisions_by_room", "decisions", ["room_id", "status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("decisions_by_room", table_name="decisions")
    op.drop_table("decisions")
