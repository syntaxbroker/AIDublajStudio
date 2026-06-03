from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import SessionLocal


class HealthService:
    def check_db(self) -> None:
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
        except Exception as exc:
            raise AppError("DB_UNAVAILABLE", "Database is unavailable", 503) from exc

    def check_redis(self) -> None:
        try:
            import redis

            client = redis.from_url(get_settings().redis_url)
            client.ping()
        except Exception as exc:
            raise AppError("REDIS_UNAVAILABLE", "Redis is unavailable", 503) from exc
