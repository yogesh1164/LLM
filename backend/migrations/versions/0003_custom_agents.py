"""Add storage for Agent Studio custom agent configurations."""

import sqlalchemy as sa
from alembic import op

revision = "0003_custom_agents"
down_revision = "0002_stage_elapsed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_agents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("system_instructions", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_custom_agents_name_ci", "custom_agents", [sa.text("lower(name)")], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_custom_agents_name_ci", table_name="custom_agents")
    op.drop_table("custom_agents")
