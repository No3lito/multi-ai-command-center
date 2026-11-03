"""conclude, don't loop

- runs.verdict: the brief's verdict (done, blocked, needs_you).
- runs.chain_root_id / chain_depth: follow-up chains, for the round limit and shared budget.
- runs.wrap_up: the owner asked the run to conclude now.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-03 10:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("verdict", sa.String(length=16), nullable=True))
    op.add_column("runs", sa.Column("chain_root_id", sa.String(length=40), nullable=True))
    op.add_column("runs", sa.Column("chain_depth", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("runs", sa.Column("wrap_up", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_index("runs_by_chain", "runs", ["chain_root_id"], unique=False)


def downgrade() -> None:
    op.drop_index("runs_by_chain", table_name="runs")
    op.drop_column("runs", "wrap_up")
    op.drop_column("runs", "chain_depth")
    op.drop_column("runs", "chain_root_id")
    op.drop_column("runs", "verdict")
