"""identity routines sessions

Revision ID: 0001_identity_routines_sessions
Revises:
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_identity_routines_sessions"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_user_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("provider", "provider_user_id"),
    )
    op.create_table(
        "training_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("routine_id", sa.Integer()),
        sa.Column("scheduled_date", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("completed_at", sa.Text()),
        sa.Column("evaluated_at", sa.Text()),
        sa.Column("evaluation_json", sa.Text()),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", "scheduled_date", "routine_id"),
    )
    op.create_index(
        "idx_training_sessions_user_date",
        "training_sessions",
        ["user_id", "scheduled_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_training_sessions_user_date", table_name="training_sessions")
    op.drop_table("training_sessions")
    op.drop_table("external_identities")
