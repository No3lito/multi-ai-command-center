"""attachments and decision briefs

- run_attachments: read-only snapshots of owner-chosen files, taken when a run starts.
- runs.brief / pending_decisions / write_brief: the decision brief that ends a run.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03 01:20:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_attachments",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("run_attachments_by_run", "run_attachments", ["run_id"], unique=False)
    op.add_column("runs", sa.Column("brief", sa.Text(), nullable=True))
    op.add_column(
        "runs", sa.Column("pending_decisions", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "runs", sa.Column("write_brief", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("runs", "write_brief")
    op.drop_column("runs", "pending_decisions")
    op.drop_column("runs", "brief")
    op.drop_index("run_attachments_by_run", table_name="run_attachments")
    op.drop_table("run_attachments")
