"""Add independent saved custom workflows and execution history.

Revision ID: 0005_custom_workflows
Revises: 0004_custom_agent_executions
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_custom_workflows"
down_revision = "0004_custom_agent_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("custom_workflows",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("custom_workflow_steps",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("custom_workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Uuid(as_uuid=True), sa.ForeignKey("custom_agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("workflow_id", "position", name="uq_custom_workflow_position"))
    op.create_index("ix_custom_workflow_steps_workflow_id", "custom_workflow_steps", ["workflow_id"])
    op.create_table("custom_workflow_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("custom_workflows.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_name", sa.String(100), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_custom_workflow_runs_workflow_id", "custom_workflow_runs", ["workflow_id"])
    op.create_table("custom_workflow_step_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), sa.ForeignKey("custom_workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True))
    op.create_index("ix_custom_workflow_step_runs_run_id", "custom_workflow_step_runs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_custom_workflow_step_runs_run_id", table_name="custom_workflow_step_runs")
    op.drop_table("custom_workflow_step_runs")
    op.drop_index("ix_custom_workflow_runs_workflow_id", table_name="custom_workflow_runs")
    op.drop_table("custom_workflow_runs")
    op.drop_index("ix_custom_workflow_steps_workflow_id", table_name="custom_workflow_steps")
    op.drop_table("custom_workflow_steps")
    op.drop_table("custom_workflows")
