"""run trees and true spend

Adds runs.root_run_id so limits and budgets apply to a whole tree of runs started by one human
action, and drops the spend_cap_not_exceeded check so a provider overrun is recorded truthfully
instead of being clamped (new reservations are still refused once the cap is reached).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02 14:56:17.282243
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("root_run_id", sa.String(length=40), nullable=True))
    op.execute("UPDATE runs SET root_run_id = id WHERE root_run_id IS NULL")
    op.create_index("runs_by_root", "runs", ["root_run_id"], unique=False)
    op.drop_constraint("spend_cap_not_exceeded", "spend_caps", type_="check")


def downgrade() -> None:
    op.execute(
        "UPDATE spend_caps SET cap_usd = spent_usd + reserved_usd WHERE spent_usd + reserved_usd > cap_usd"
    )
    op.create_check_constraint(
        "spend_cap_not_exceeded", "spend_caps", "spent_usd + reserved_usd <= cap_usd + 0.000001"
    )
    op.drop_index("runs_by_root", table_name="runs")
    op.drop_column("runs", "root_run_id")
