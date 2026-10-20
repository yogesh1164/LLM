"""Record per stage elapsed time."""

import sqlalchemy as sa
from alembic import op

revision = "0002_stage_elapsed"
down_revision = "0001_workflow_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_executions", sa.Column("elapsed_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_executions", "elapsed_ms")
