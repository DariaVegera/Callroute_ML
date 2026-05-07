"""
Cron-задача: еженедельный кэшбэк на бонусный счёт.
"""
import logging
from worker.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="worker.tasks.cashback_task.calculate_weekly_cashback")
def calculate_weekly_cashback():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timezone, timedelta
    from api.core.config import settings

    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        week_start = datetime.now(timezone.utc) - timedelta(days=7)

        # Сумма списаний за неделю по каждому пользователю
        rows = db.execute(text("""
            SELECT t.user_id, SUM(t.amount) as total_spent,
                   u.loyalty_level
            FROM transactions t
            JOIN users u ON u.id = t.user_id
            WHERE t.type = 'DEBIT_PREDICTION'
              AND t.created_at >= :week_start
            GROUP BY t.user_id, u.loyalty_level
        """), {"week_start": week_start}).fetchall()

        # Процент кэшбэка из loyalty_levels
        levels = {
            row.name: float(row.cashback_percent)
            for row in db.execute(text(
                "SELECT name, cashback_percent FROM loyalty_levels"
            )).fetchall()
        }

        processed = 0
        for row in rows:
            cashback_pct = levels.get(row.loyalty_level, 1.0)
            cashback = float(row.total_spent) * cashback_pct / 100

            if cashback <= 0:
                continue

            # Начислить на bonus
            db.execute(text("""
                UPDATE user_balances 
                SET bonus_credits = bonus_credits + :cashback, version = version + 1, updated_at = NOW()
                WHERE user_id = :uid
            """), {"cashback": cashback, "uid": row.user_id})

            # Записать транзакцию
            db.execute(text("""
                INSERT INTO transactions (id, user_id, type, amount, balance_type, 
                    balance_before, balance_after, description, reference_type, created_at)
                SELECT gen_random_uuid(), :uid, 'CREDIT_CASHBACK', :amount, 'bonus',
                    bonus_credits - :amount, bonus_credits, 
                    :desc, 'cashback', NOW()
                FROM user_balances WHERE user_id = :uid
            """), {
                "uid": row.user_id,
                "amount": cashback,
                "desc": f"Weekly cashback {cashback_pct}% on {row.total_spent:.2f} credits spent",
            })

            # Лог кэшбэка
            db.execute(text("""
                INSERT INTO weekly_cashback_log (id, user_id, week_start, total_spent, cashback_amount, created_at)
                VALUES (gen_random_uuid(), :uid, :week_start, :spent, :cashback, NOW())
            """), {
                "uid": row.user_id,
                "week_start": week_start,
                "spent": float(row.total_spent),
                "cashback": cashback,
            })
            processed += 1

        db.commit()
        logger.info(f"Weekly cashback: {processed} users received cashback")

    except Exception as e:
        db.rollback()
        logger.exception(f"Cashback task failed: {e}")
    finally:
        db.close()
        engine.dispose()
