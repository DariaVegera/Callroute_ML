"""Initial schema with seed data

Revision ID: 0001
Revises: 
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import uuid

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === USERS ===
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255)),
        sa.Column('role', sa.String(50), server_default='user'),
        sa.Column('loyalty_level', sa.String(20), server_default='bronze'),
        sa.Column('predictions_this_month', sa.Integer(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # === USER BALANCES ===
    op.create_table(
        'user_balances',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('bought_credits', sa.Numeric(12, 2), server_default='0.00'),
        sa.Column('bonus_credits', sa.Numeric(12, 2), server_default='0.00'),
        sa.Column('version', sa.BigInteger(), server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # === TRANSACTIONS ===
    op.create_table(
        'transactions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('balance_type', sa.String(20), nullable=False),
        sa.Column('balance_before', sa.Numeric(12, 2), nullable=False),
        sa.Column('balance_after', sa.Numeric(12, 2), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('reference_id', UUID(as_uuid=True)),
        sa.Column('reference_type', sa.String(50)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_transactions_user_id', 'transactions', ['user_id'])
    op.create_index('idx_transactions_created_at', 'transactions', ['created_at'])

    # === LOYALTY LEVELS ===
    op.create_table(
        'loyalty_levels',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(20), unique=True, nullable=False),
        sa.Column('min_predictions', sa.Integer(), server_default='0'),
        sa.Column('discount_percent', sa.Numeric(5, 2), server_default='0.00'),
        sa.Column('cashback_percent', sa.Numeric(5, 2), server_default='0.00'),
        sa.Column('description', sa.Text()),
    )

    # === REFERRAL CODES ===
    op.create_table(
        'referral_codes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('code', sa.String(50), unique=True, nullable=False),
        sa.Column('bonus_per_referral', sa.Numeric(12, 2), server_default='50.00'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # === REFERRAL EVENTS ===
    op.create_table(
        'referral_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('referrer_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('referred_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('bonus_credited', sa.Numeric(12, 2), server_default='0.00'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # === WEEKLY CASHBACK LOG ===
    op.create_table(
        'weekly_cashback_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('week_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_spent', sa.Numeric(12, 2), server_default='0.00'),
        sa.Column('cashback_amount', sa.Numeric(12, 2), server_default='0.00'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # === ML MODELS ===
    op.create_table(
        'ml_models',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('model_key', sa.String(100), unique=True, nullable=False),
        sa.Column('artifact_path', sa.String(500), nullable=False),
        sa.Column('metrics', sa.JSON()),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # === PREDICTION TIERS ===
    op.create_table(
        'prediction_tiers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(50), unique=True, nullable=False),
        sa.Column('model_key', sa.String(100), nullable=False),
        sa.Column('base_cost', sa.Numeric(12, 2), nullable=False),
        sa.Column('max_input_chars', sa.Integer(), server_default='5000'),
        sa.Column('description', sa.Text()),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # === PREDICTION TASKS ===
    op.create_table(
        'prediction_tasks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('tier_id', UUID(as_uuid=True), sa.ForeignKey('prediction_tiers.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(255), unique=True, nullable=False),
        sa.Column('input_text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(30), server_default='pending'),
        sa.Column('predicted_intent', sa.String(100)),
        sa.Column('predicted_priority', sa.String(20)),
        sa.Column('queue_recommendation', sa.String(100)),
        sa.Column('confidence_score', sa.Numeric(5, 4)),
        sa.Column('low_confidence', sa.Boolean(), server_default='false'),
        sa.Column('credits_charged', sa.Numeric(12, 2)),
        sa.Column('error_message', sa.Text()),
        sa.Column('celery_task_id', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('idx_prediction_tasks_user_id', 'prediction_tasks', ['user_id'])
    op.create_index('idx_prediction_tasks_status', 'prediction_tasks', ['status'])

    # === HITL TASKS ===
    op.create_table(
        'hitl_tasks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('prediction_task_id', UUID(as_uuid=True), sa.ForeignKey('prediction_tasks.id'), nullable=False),
        sa.Column('input_text', sa.Text(), nullable=False),
        sa.Column('model_prediction', sa.String(100), nullable=False),
        sa.Column('model_confidence', sa.Numeric(5, 4), nullable=False),
        sa.Column('correct_label', sa.String(100)),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('reward_credits', sa.Numeric(12, 2), server_default='5.00'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
    )

    # === HITL COMPLETIONS ===
    op.create_table(
        'hitl_completions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('hitl_task_id', UUID(as_uuid=True), sa.ForeignKey('hitl_tasks.id'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('label_chosen', sa.String(100), nullable=False),
        sa.Column('bonus_credited', sa.Numeric(12, 2), server_default='0.00'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # =====================
    # SEED DATA
    # =====================

    # Loyalty levels
    op.execute("""
        INSERT INTO loyalty_levels (id, name, min_predictions, discount_percent, cashback_percent, description) VALUES
        (gen_random_uuid(), 'bronze', 0,   0.00, 1.00, 'Default level — 1% cashback'),
        (gen_random_uuid(), 'silver', 100, 5.00, 3.00, '100+ predictions/month — 5% discount, 3% cashback'),
        (gen_random_uuid(), 'gold',   500, 10.00, 5.00, '500+ predictions/month — 10% discount, 5% cashback')
    """)

    # Prediction tiers
    op.execute("""
        INSERT INTO prediction_tiers (id, name, model_key, base_cost, max_input_chars, description) VALUES
        (gen_random_uuid(), 'fast',  'catboost_tfidf', 1.00, 5000, 'TF-IDF + CatBoost, <100ms'),
        (gen_random_uuid(), 'smart', 'rubert_tiny2',   3.00, 5000, 'rubert-tiny2 finetune, <500ms'),
        (gen_random_uuid(), 'batch', 'rubert_tiny2',   2.00, 5000, 'Async batch processing')
    """)

    # ML models (placeholders — artifacts loaded at runtime)
    op.execute("""
        INSERT INTO ml_models (id, name, version, model_key, artifact_path, metrics) VALUES
        (gen_random_uuid(), 'CatBoost TF-IDF', '1.0.0', 'catboost_tfidf', '/app/models/catboost_model.cbm', '{"accuracy": 0.0, "f1": 0.0}'),
        (gen_random_uuid(), 'rubert-tiny2',    '1.0.0', 'rubert_tiny2',   '/app/models/smart_model',        '{"accuracy": 0.0, "f1": 0.0}')
    """)


def downgrade() -> None:
    op.drop_table('hitl_completions')
    op.drop_table('hitl_tasks')
    op.drop_table('prediction_tasks')
    op.drop_table('prediction_tiers')
    op.drop_table('ml_models')
    op.drop_table('weekly_cashback_log')
    op.drop_table('referral_events')
    op.drop_table('referral_codes')
    op.drop_table('transactions')
    op.drop_table('user_balances')
    op.drop_table('loyalty_levels')
    op.drop_table('users')
