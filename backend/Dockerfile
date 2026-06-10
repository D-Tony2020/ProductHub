FROM python:3.12-slim

WORKDIR /srv/app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

RUN pip install .

EXPOSE 8000
# 发布流程：先跑迁移再起服务（见 deploy/docker-compose.prod.yml command）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
