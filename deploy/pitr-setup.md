# PITR 时点恢复（WAL-G）— 单机过渡期方案

> 目标：把 RPO 从"日备份的 24h"压到**分钟/秒级**（可恢复到崩溃前任意时点）。
> 定位：**单机过渡期的桥**。迁移到托管 Postgres（阿里云 RDS / 腾讯云等）后，PITR + 多 AZ 由云厂商内置提供，本方案即可退役。
> 工具选 WAL-G（单二进制、archive_command 友好）；pgBackRest 亦可，二选一。

## 原理
持续把 WAL（预写日志）归档到对象存储 + 周期基础备份。恢复时 = 基础备份 + 重放 WAL 到目标时点。

## 1. 让 postgres 容器具备 wal-g
新建 `deploy/postgres-walg.Dockerfile`：
```dockerfile
FROM postgres:16
ARG WALG_VERSION=v3.0.5
ADD https://github.com/wal-g/wal-g/releases/download/${WALG_VERSION}/wal-g-pg-ubuntu-20.04-amd64.tar.gz /tmp/walg.tgz
RUN tar -xzf /tmp/walg.tgz -C /usr/local/bin && mv /usr/local/bin/wal-g-pg-ubuntu-20.04-amd64 /usr/local/bin/wal-g && rm /tmp/walg.tgz
```
compose 中 postgres 改 `build: { context: ., dockerfile: postgres-walg.Dockerfile }`，并注入 WAL-G 环境（走 .env.prod，密钥不入仓）：
```yaml
    environment:
      POSTGRES_USER: producthub
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}
      POSTGRES_DB: producthub
      WALG_S3_PREFIX: ${WALG_S3_PREFIX:?}          # 如 s3://producthub-wal（OSS/COS 兼容 S3 协议）
      AWS_ACCESS_KEY_ID: ${WALG_KEY_ID:?}
      AWS_SECRET_ACCESS_KEY: ${WALG_KEY_SECRET:?}
      AWS_ENDPOINT: ${WALG_ENDPOINT:?}             # OSS/COS 的 S3 兼容端点
      WALG_COMPRESSION_METHOD: brotli
```

## 2. 开启归档（postgresql.conf）
通过 command 或挂载 conf 设：
```
wal_level = replica
archive_mode = on
archive_command = 'wal-g wal-push %p'
archive_timeout = 60          # 即使低写入，也每 60s 切一段 WAL → RPO 上限约 60s
```
（compose 里可用 `command: postgres -c wal_level=replica -c archive_mode=on -c "archive_command=wal-g wal-push %p" -c archive_timeout=60`。注意 app 服务的迁移命令不受影响。）

## 3. 基础备份（每日，cron）
```sh
docker compose -f /opt/producthub/deploy/docker-compose.prod.yml exec -T postgres \
  wal-g backup-push /var/lib/postgresql/data
#  cron:  0 1 * * *  ...（排在逻辑备份/同步之外，互为冗余）
```

## 4. 时点恢复（PITR 演练 / 真实灾难）
```sh
# 停 app/caddy；在一个干净数据目录恢复基础备份后重放 WAL 到目标时点：
docker compose ... exec -T postgres wal-g backup-fetch /var/lib/postgresql/data LATEST
# 在数据目录写 recovery 配置：
#   restore_command = 'wal-g wal-fetch %f %p'
#   recovery_target_time = '2026-06-19 14:30:00+08'
#   touch recovery.signal
# 重启 postgres，PG 重放 WAL 到该时点后开放。
```
> 真实灾难恢复进生产库属高风险操作，先在隔离环境演练（见 docs/数据安全与灾备策略.md 的演练 SOP）。

## 5. 验证（必须，否则等于没配）
- 配置后查 `SELECT * FROM pg_stat_archiver;`（archived_count 增长、failed_count=0）。
- 对象存储能看到 WAL 段与 basebackup。
- **每月一次 PITR 演练**：恢复到隔离实例并对某时点核验数据，记录 RPO 实测值。

## 退役条件
迁移到托管 Postgres 后：关闭本方案，改用云厂商的自动备份 + 一键 PITR + 多 AZ；保留逻辑 dump 异地副本作为跨厂商兜底（仍跑 backup.sh + offsite-sync.sh + customer-pull.ps1）。
