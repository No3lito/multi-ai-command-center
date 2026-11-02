"""agent output limit 2048

The first real collaboration showed 1024 output tokens cut Claude's plans off mid-sentence.
Agents still on the old 1024 default move to 2048; any other value the owner chose is kept.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02 20:35:00
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE agent_profiles SET max_output_tokens = 2048 WHERE max_output_tokens = 1024")


def downgrade() -> None:
    op.execute("UPDATE agent_profiles SET max_output_tokens = 1024 WHERE max_output_tokens = 2048")
