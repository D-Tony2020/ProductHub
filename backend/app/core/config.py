from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRODUCTHUB_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub"
    # JWT 密钥：必填、代码内零默认值（缺失即启动失败），≥32 字节。生产由环境/密钥管理注入，
    # dev 见 backend/.env、测试见 conftest。绝不在代码留可用默认值——否则任何人凭公开默认串即可
    # 离线伪造管理员令牌、绕过登录直踩"数据库绝不能数据混乱"红线。
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    default_currency: str = "USD"
    # 配置树最大深度：DAG 防环之外的纵深防御
    max_config_depth: int = 10
    # 业务时区：固定每个连接的会话时区，使 CURRENT_DATE/now()(视图、现价口径)
    # 与应用侧 date.today() 同口径，避免容器 UTC 与本地差日导致"当天录价当天报不了"
    db_timezone: str = "Asia/Shanghai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
