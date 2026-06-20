-- 双租户内测：PG 首次初始化时额外创建 B 套(余姚宇盛)独立库，与 A 套(producthub)物理隔离。
-- 仅在 pgdata 卷为空的首次初始化时执行（标准 postgres entrypoint 行为）。
CREATE DATABASE producthub_b OWNER producthub;
