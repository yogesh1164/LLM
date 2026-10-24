"""Add accounts and nullable ownership; never assign legacy data implicitly."""
import sqlalchemy as sa
from alembic import op

revision = "0007_accounts_ownership"
down_revision = "0006_durable_executions"
branch_labels = None
depends_on = None

OWNED_TABLES = ("tasks", "custom_agents", "custom_agent_executions", "custom_workflows",
                "custom_workflow_runs", "durable_executions")


def upgrade() -> None:
    op.create_table("users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("login", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credential_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_user_role"))
    op.create_table("account_sessions",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("csrf_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.create_index("ix_account_sessions_user_id", "account_sessions", ["user_id"])
    op.create_index("ix_account_sessions_expires_at", "account_sessions", ["expires_at"])
    op.create_table("account_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("actor", sa.String(254), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_account_audit_user_id", "account_audit", ["user_id"])
    op.create_table("login_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False))
    op.create_table("ownership_assignments",
        sa.Column("manifest_digest", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_by", sa.String(254), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False))
    for table in OWNED_TABLES:
        # batch mode also supports isolated SQLite migration fixtures.
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("owner_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_owner", "users", ["owner_id"], ["id"],
                                     ondelete="RESTRICT")
            batch.create_index(f"ix_{table}_owner_id", ["owner_id"])
    if op.get_bind().dialect.name != "sqlite":
        op.drop_index("uq_custom_agents_name_ci", table_name="custom_agents")
    # SQLite's batch recreation omits the old expression index automatically.
    op.create_index("uq_custom_agents_owner_name_ci", "custom_agents",
                    ["owner_id", sa.text("lower(name)")], unique=True)
    op.create_index("uq_custom_agents_legacy_name_ci", "custom_agents", [sa.text("lower(name)")],
                    unique=True, postgresql_where=sa.text("owner_id IS NULL"),
                    sqlite_where=sa.text("owner_id IS NULL"))


def downgrade() -> None:
    raise RuntimeError("Account/ownership removal requires explicit data retention and recovery review")
