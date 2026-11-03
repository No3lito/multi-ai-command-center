"""code jobs

- runs.kind 'code': Claude and GPT change the Command Center's code through a pull request.
- runs.code_state: the job's GitHub state (branch, pull request, commits, CI, review).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-03 11:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("run_kind", "runs", type_="check")
    op.create_check_constraint("run_kind", "runs", "kind in ('collab','reply','build','review','code')")
    op.add_column("runs", sa.Column("code_state", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "code_state")
    op.execute("DELETE FROM runs WHERE kind = 'code'")
    op.drop_constraint("run_kind", "runs", type_="check")
    op.create_check_constraint("run_kind", "runs", "kind in ('collab','reply','build','review')")
