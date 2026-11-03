"""build workflow and agent roles

- runs.builder_id and run kind 'build' (design & build workflow).
- The owner's chosen roles: Claude and GPT are co-designers with one goal; Grok builds.
  Default agents still on the original role and prompt are updated; anything the owner
  customized is left alone.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02 21:20:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OLD = {
    "Claude": (
        "Planner",
        "You lead planning. Turn goals into clear, ordered, testable steps, and say what you would "
        "verify. When reviewing others, be specific and kind.",
    ),
    "GPT": (
        "Reviewer",
        "You lead review. Find gaps, risks and simpler alternatives, and suggest concrete fixes. "
        "When asked to plan, keep plans short and practical.",
    ),
}
NEW = {
    "Claude": (
        "Co-designer",
        "You are a co-designer. You and your fellow designer share one goal: give the owner exactly "
        "what they need. Turn goals into clear, concrete, buildable designs and say how to verify "
        "them. When a builder implements your design, give precise instructions, down to the code "
        "where it matters.",
    ),
    "GPT": (
        "Co-designer",
        "You are a co-designer. You and your fellow designer share one goal: give the owner exactly "
        "what they need. As an equal partner, find gaps, risks and simpler options and fold them "
        "into the design. When a builder implements it, check the result and give precise fix "
        "instructions.",
    ),
}

UPDATE = sa.text(
    "UPDATE agent_profiles SET role = :new_role, system_prompt = :new_prompt "
    "WHERE role = :old_role AND system_prompt = :old_prompt AND principal_id IN "
    "(SELECT id FROM principals WHERE kind = 'agent' AND display_name = :name)"
)


def upgrade() -> None:
    op.add_column("runs", sa.Column("builder_id", sa.String(length=40), nullable=True))
    op.create_foreign_key("runs_builder_id_fkey", "runs", "principals", ["builder_id"], ["id"])
    op.drop_constraint("run_kind", "runs", type_="check")
    op.create_check_constraint("run_kind", "runs", "kind in ('collab','reply','build')")
    bind = op.get_bind()
    for name in ("Claude", "GPT"):
        (old_role, old_prompt), (new_role, new_prompt) = OLD[name], NEW[name]
        bind.execute(
            UPDATE,
            {
                "name": name,
                "old_role": old_role,
                "old_prompt": old_prompt,
                "new_role": new_role,
                "new_prompt": new_prompt,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("Claude", "GPT"):
        (old_role, old_prompt), (new_role, new_prompt) = OLD[name], NEW[name]
        bind.execute(
            UPDATE,
            {
                "name": name,
                "old_role": new_role,
                "old_prompt": new_prompt,
                "new_role": old_role,
                "new_prompt": old_prompt,
            },
        )
    op.execute("DELETE FROM runs WHERE kind = 'build'")
    op.drop_constraint("run_kind", "runs", type_="check")
    op.create_check_constraint("run_kind", "runs", "kind in ('collab','reply')")
    op.drop_constraint("runs_builder_id_fkey", "runs", type_="foreignkey")
    op.drop_column("runs", "builder_id")
