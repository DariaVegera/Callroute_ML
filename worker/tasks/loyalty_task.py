"""
Cron-задача: пересчёт уровней лояльности раз в час.
Апгрейд/даунгрейд по predictions_this_month.
"""
import logging
from celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="tasks.loyalty_task.recalculate_loyalty")
def recalculate_loyalty():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from api.core.config import settings

    db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # Подтягиваем уровни из таблицы
        levels = db.execute(text(
            "SELECT name, min_predictions FROM loyalty_levels ORDER BY min_predictions DESC"
        )).fetchall()

        if not levels:
            return

        # Обновляем уровень каждого пользователя
        users = db.execute(text(
            "SELECT id, predictions_this_month, loyalty_level FROM users WHERE is_active = true"
        )).fetchall()

        updated = 0
        for user in users:
            new_level = levels[-1].name  # lowest default
            for level in levels:
                if user.predictions_this_month >= level.min_predictions:
                    new_level = level.name
                    break

            if new_level != user.loyalty_level:
                db.execute(text(
                    "UPDATE users SET loyalty_level = :level, updated_at = NOW() WHERE id = :uid"
                ), {"level": new_level, "uid": user.id})
                updated += 1

        # Сбрасываем месячный счётчик в конце месяца (упрощённо: при каждом запуске часа 0:00)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute < 60:
            db.execute(text("UPDATE users SET predictions_this_month = 0"))

        db.commit()
        logger.info(f"Loyalty recalculated: {updated} users updated")

    except Exception as e:
        db.rollback()
        logger.exception(f"Loyalty task failed: {e}")
    finally:
        db.close()
        engine.dispose()
