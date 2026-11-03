"""agent output limit 8000

Claude 5.5 thinks before answering and thinking counts toward the output limit; at 2048 a
review answer came back empty. Agents still on the 2048 default move to 8000 (the cap still
reserves the worst case before every call); anything the owner chose is kept.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03 00:50:00
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE agent_profiles SET max_output_tokens = 8000 WHERE max_output_tokens = 2048")


def downgrade() -> None:
    op.execute("UPDATE agent_profiles SET max_output_tokens = 2048 WHERE max_output_tokens = 8000")
