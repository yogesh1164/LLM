"""Add opt-in execution journal; no legacy backfill or ownership changes.

Revision ID: 0006_durable_executions
Revises: 0005_custom_workflows
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_durable_executions"
down_revision = "0005_custom_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "durable_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("key_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_started", sa.Boolean(), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                  nullable=True, unique=True),
        sa.Column("agent_execution_id", sa.Uuid(),
                  sa.ForeignKey("custom_agent_executions.id", ondelete="SET NULL"),
                  nullable=True, unique=True),
        sa.Column("workflow_run_id", sa.Uuid(),
                  sa.ForeignKey("custom_workflow_runs.id", ondelete="SET NULL"),
                  nullable=True, unique=True),
        sa.UniqueConstraint("scope", "key_digest", name="uq_durable_scope_key"),
        sa.CheckConstraint("state IN ('running', 'completed', 'failed', 'interrupted')",
                           name="ck_durable_state"),
        sa.CheckConstraint("(CASE WHEN task_id IS NULL THEN 0 ELSE 1 END + "
                           "CASE WHEN agent_execution_id IS NULL THEN 0 ELSE 1 END + "
                           "CASE WHEN workflow_run_id IS NULL THEN 0 ELSE 1 END) <= 1",
                           name="ck_durable_one_target"),
    )
    op.create_index("ix_durable_expiry", "durable_executions", ["state", "lease_expires_at"])


def downgrade() -> None:
    # Deliberately refuse to erase idempotency tombstones automatically.
    raise RuntimeError("Durable journal removal requires an explicit retention/rollback decision")
