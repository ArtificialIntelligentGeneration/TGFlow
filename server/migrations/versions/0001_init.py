"""init schema

Revision ID: 0001
Revises: 
Create Date: 2025-09-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("device_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "plans",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("monthly_limit", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
    )
    op.create_index("ix_plans_name", "plans", ["name"], unique=True)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"], unique=False)
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"], unique=False)

    op.create_table(
        "usages",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("month_key", sa.String(length=7), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "month_key", name="uq_usage_user_month"),
    )
    op.create_index("ix_usages_user_id", "usages", ["user_id"], unique=False)
    op.create_index("ix_usages_month_key", "usages", ["month_key"], unique=False)

    op.create_table(
        "reservations",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("messages", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "correlation_id", name="uq_reservation_user_correlation"),
    )
    op.create_index("ix_reservations_user_id", "reservations", ["user_id"], unique=False)
    op.create_index("ix_reservations_expires_at", "reservations", ["expires_at"], unique=False)
    op.create_index("ix_reservations_committed", "reservations", ["committed"], unique=False)
    op.create_index("ix_reservations_correlation_id", "reservations", ["correlation_id"], unique=False)


def downgrade() -> None:
    op.drop_table("reservations")
    op.drop_table("usages")
    op.drop_table("subscriptions")
    op.drop_table("plans")
    op.drop_table("users")



