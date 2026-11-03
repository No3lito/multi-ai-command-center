"""workspace projects

- rooms.project_path: the workspace project a room works on.
- runs.agent_files: the lead agent picks the project files to read.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03 09:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("project_path", sa.String(length=300), nullable=True))
    op.add_column(
        "runs", sa.Column("agent_files", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("runs", "agent_files")
    op.drop_column("rooms", "project_path")
