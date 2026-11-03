"""self-serve dashboard

- decisions.why / recommended / suggested_note: cards that explain themselves.
- runs.archived_at: finished runs the owner hid from the chat (still searchable).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03 07:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("decisions", sa.Column("why", sa.Text(), nullable=True))
    op.add_column("decisions", sa.Column("recommended", sa.String(length=16), nullable=True))
    op.add_column("decisions", sa.Column("suggested_note", sa.Text(), nullable=True))
    op.create_check_constraint(
        "decision_recommended",
        "decisions",
        "recommended is null or recommended in ('approve','decline','more_info')",
    )
    op.add_column("runs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "archived_at")
    op.drop_constraint("decision_recommended", "decisions", type_="check")
    op.drop_column("decisions", "suggested_note")
    op.drop_column("decisions", "recommended")
    op.drop_column("decisions", "why")
