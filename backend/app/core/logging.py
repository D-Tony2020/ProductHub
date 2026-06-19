"""结构化（JSON 行）日志：stdlib 实现，零新依赖。

生产容器把日志写 stdout，由 Docker/编排收集转发到 ELK/Datadog 等；JSON 行便于检索与告警。
级别由环境变量 LOG_LEVEL 控制（默认 INFO）。不在日志打印连接串/令牌/口令等敏感信息——
由各调用方自律（HTTPException 文案亦不应内嵌敏感数据，见安全审计 A2-006）。
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

_STD = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 透传调用方附加的结构化字段（logger.info(..., extra={"path": ...})）
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_") and v is not None:
                payload[k] = v
        return json.dumps(payload, ensure_ascii=False, default=str)


_CONFIGURED = False


def setup_logging() -> None:
    """安装 JSON 格式根 handler，并收编 uvicorn 三个 logger。幂等。

    注：uvicorn 以 --log-config 启动时会自管日志；如需 access 日志也走 JSON，
    在启动命令传入本模块导出的配置或用 --log-config。此处保证应用层(producthub.*)日志为 JSON。
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = [handler]
        lg.propagate = False
        lg.setLevel(level)
    _CONFIGURED = True


def get_logger(name: str = "producthub") -> logging.Logger:
    return logging.getLogger(name)
