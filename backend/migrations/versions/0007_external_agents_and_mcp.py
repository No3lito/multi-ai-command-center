"""external agents and mcp

- agent_tokens: hashed, revocable access tokens for external agents (Grok Bot over MCP).
- runs: status 'waiting' (an external agent's turn), kind 'review', waiting_* columns.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02 22:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tokens",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("principal_id", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("agent_tokens_by_principal", "agent_tokens", ["principal_id"], unique=False)
    op.add_column("runs", sa.Column("waiting_for", sa.String(length=40), nullable=True))
    op.add_column("runs", sa.Column("waiting_instruction", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("runs_waiting_for_fkey", "runs", "principals", ["waiting_for"], ["id"])
    op.create_index(
        "runs_waiting", "runs", ["waiting_for"], unique=False, postgresql_where=sa.text("status = 'waiting'")
    )
    op.drop_constraint("run_kind", "runs", type_="check")
    op.create_check_constraint("run_kind", "runs", "kind in ('collab','reply','build','review')")
    op.drop_constraint("run_status", "runs", type_="check")
    op.create_check_constraint(
        "run_status",
        "runs",
        "status in ('queued','running','waiting','completed','failed','cancelled','budget_exceeded')",
    )


def downgrade() -> None:
    op.execute("UPDATE runs SET status = 'cancelled', finished_at = now() WHERE status = 'waiting'")
    op.execute("DELETE FROM runs WHERE kind = 'review'")
    op.drop_constraint("run_status", "runs", type_="check")
    op.create_check_constraint(
        "run_status",
        "runs",
        "status in ('queued','running','completed','failed','cancelled','budget_exceeded')",
    )
    op.drop_constraint("run_kind", "runs", type_="check")
    op.create_check_constraint("run_kind", "runs", "kind in ('collab','reply','build')")
    op.drop_index("runs_waiting", table_name="runs", postgresql_where=sa.text("status = 'waiting'"))
    op.drop_constraint("runs_waiting_for_fkey", "runs", type_="foreignkey")
    op.drop_column("runs", "waiting_since")
    op.drop_column("runs", "waiting_instruction")
    op.drop_column("runs", "waiting_for")
    op.drop_index("agent_tokens_by_principal", table_name="agent_tokens")
    op.drop_table("agent_tokens")
