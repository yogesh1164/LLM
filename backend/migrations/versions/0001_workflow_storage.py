"""Create persistent workflow tasks and agent execution stages."""

import sqlalchemy as sa
from alembic import op

revision = "0001_workflow_storage"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("estimated_cost", sa.Float()),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("output", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
    )
    op.create_index("ix_agent_executions_task_id", "agent_executions", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_executions_task_id", table_name="agent_executions")
    op.drop_table("agent_executions")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_table("tasks")
