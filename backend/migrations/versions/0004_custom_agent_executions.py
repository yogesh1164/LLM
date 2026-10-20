"""Persist executions of Agent Studio custom agents."""

import sqlalchemy as sa
from alembic import op

revision = "0004_custom_agent_executions"
down_revision = "0003_custom_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_agent_executions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["custom_agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_custom_agent_executions_agent_id", "custom_agent_executions", ["agent_id"])
    op.create_index("ix_custom_agent_executions_status", "custom_agent_executions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_custom_agent_executions_status", table_name="custom_agent_executions")
    op.drop_index("ix_custom_agent_executions_agent_id", table_name="custom_agent_executions")
    op.drop_table("custom_agent_executions")
