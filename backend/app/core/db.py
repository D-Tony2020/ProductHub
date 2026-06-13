from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
# 固定会话时区为业务时区：CURRENT_DATE/now() 与应用侧 date.today() 同口径，
# 杜绝容器 UTC 与本地差日导致的现价视图边界漏算（录价当天报不了）。psycopg3 连接选项。
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    connect_args={"options": f"-c timezone={_settings.db_timezone}"},
)

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
