from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求一个 Session，service 层负责 commit，异常回滚。"""
    db = SessionLocal()
    try:
        yield db
        db.rollback()  # 未显式 commit 的读事务正常结束
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
