# ProductHub 产品中台

北京合胜（灭火器外贸）产品库 + SKU 配置 + 报价系统。

**单一事实源承诺**：一个配置只有一个 SKU（规范化指纹唯一）；一个 SKU 任一时点只有一条现价（append-only 价格史 + 生效期排他约束）。

## 技术栈

- 后端：Python / FastAPI / SQLAlchemy 2.0（sync）/ Alembic / PostgreSQL 16（btree_gist, pg_trgm）
- 前端：Vue 3 / TypeScript / Element Plus / Pinia / Vite
- 部署：Docker Compose（caddy + app + postgres），香港轻量云主机

## 本地开发

```powershell
# 1. 启动开发数据库（宿主端口 5440）
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. 后端
cd backend
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
copy .env.example .env
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m scripts.seed          # 灭火器示例模板 + admin 账号
.venv\Scripts\uvicorn app.main:app --reload   # http://127.0.0.1:8000/docs

# 3. 测试（需要 dev 数据库在运行）
.venv\Scripts\python -m pytest

# 4. 前端
cd ../frontend
npm install
npm run dev                                    # http://127.0.0.1:5173
```

## 目录

```
backend/   FastAPI 应用、Alembic 迁移、pytest
frontend/  Vue3 SPA
deploy/    docker compose（dev/prod）、Caddyfile、备份脚本
docs/      项目内技术文档（需求/设计正本在客户工作空间 03-需求、04-设计）
```

## 设计文档

- SRS：`../03-需求/SRS-ProductHub-v1.md`
- HLD：`../04-设计/HLD-ProductHub-v1.md`
- 数据红线与边界场景结论：见 HLD §3 与立项规划
