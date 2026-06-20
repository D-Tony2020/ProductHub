# 单机自管 PITR：在官方 postgres:16(Debian) 上直装 pgBackRest（Debian 官方源，稳健）。
# pgBackRest 负责：连续 WAL 归档 + 全量/增量基础备份 + 保留策略 + 时点恢复(PITR)，可推本地或 S3/OSS。
FROM postgres:16
RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbackrest \
    && rm -rf /var/lib/apt/lists/*
# pgbackrest.conf 由 compose 挂载到 /etc/pgbackrest/pgbackrest.conf；
# 归档命令、stanza 等见 docs/部署方案-单机自管.md。
