"""decision options

- decisions.options: 2 to 4 ready-made answers the agents prepared (label, detail, answer,
  note), so the owner can pick one instead of writing a note.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-03 16:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("decisions", sa.Column("options", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("decisions", "options")
