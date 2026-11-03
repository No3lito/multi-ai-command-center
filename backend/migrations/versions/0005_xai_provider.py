"""xai provider

Allows agents with provider 'xai' (Grok).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02 21:10:00
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("agent_provider", "agent_profiles", type_="check")
    op.create_check_constraint(
        "agent_provider", "agent_profiles", "provider in ('anthropic','openai','xai','simulated')"
    )


def downgrade() -> None:
    op.execute("UPDATE agent_profiles SET enabled = false, provider = 'simulated' WHERE provider = 'xai'")
    op.drop_constraint("agent_provider", "agent_profiles", type_="check")
    op.create_check_constraint(
        "agent_provider", "agent_profiles", "provider in ('anthropic','openai','simulated')"
    )
