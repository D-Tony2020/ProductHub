from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
# 固定会话时区为业务时区：CURRENT_DATE/now() 与应用侧 date.today() 同口径，
# 杜绝容器 UTC 与本地差日导致的现价视图边界漏算（录价当天报不了）。psycopg3 连接选项。
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,        # 取连接前探活，自动剔除已失效连接(PG 重启/超时后免 500)
    pool_size=10,              # 常驻连接(默认仅 5)
    max_overflow=20,           # 峰值额外连接 → 单进程上限 30
    pool_timeout=30,           # 池满时取连接的等待上限(秒)，超时即报错而非无限挂起
    pool_recycle=1800,         # 连接最长存活 30 分钟后回收，避开服务端空闲断连
    connect_args={"options": f"-c timezone={_settings.db_timezone}"},
)
# 注：每进程连接上限 = pool_size + max_overflow = 30。多 worker 部署时
#     workers × 30 必须 < Postgres max_connections(默认 100)，或前置 PgBouncer。

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
