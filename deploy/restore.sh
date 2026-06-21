#!/bin/sh
# 恢复演练：把 pg_dump 自定义格式备份恢复到一个隔离库（默认 producthub_restore_test）并核验行数。
# "备份不验证恢复 = 没有备份"——建议每月跑一次。演练不触碰生产库 producthub。
# 真正灾难恢复（恢复进 producthub）见 docs/部署运维指南.md 的「回滚与灾难恢复」。
#
# 用法： ./restore.sh /opt/producthub/backups/producthub-YYYYmmdd-HHMMSS.dump [目标库名]
set -eu

DUMP="${1:?用法: restore.sh <dump 文件路径> [目标库名，默认 producthub_restore_test]}"
TARGET="${2:-producthub_restore_test}"
# 物理护栏：演练绝不允许恢复到任何生产/系统库（防参数手滑或提示注入删库）。
# 真正的灾难恢复（恢复进生产）走 docs/部署运维指南.md 的专门审批流程，不经此脚本。
case "$TARGET" in
  producthub|producthub_b|postgres|template*) echo "[restore] 拒绝：禁止恢复到生产/系统库「$TARGET」；演练只允许隔离库（如 producthub_restore_test）" >&2; exit 9 ;;
esac
COMPOSE="${COMPOSE:-/opt/producthub/deploy/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-}"
ENVARG=""; [ -n "$ENV_FILE" ] && ENVARG="--env-file $ENV_FILE"

[ -f "$DUMP" ] || { echo "[restore] 找不到备份文件: $DUMP" >&2; exit 1; }
echo "[restore] 目标隔离库: $TARGET  来源备份: $DUMP"

docker compose $ENVARG -f "$COMPOSE" exec -T postgres psql -U producthub -d postgres \
  -c "DROP DATABASE IF EXISTS $TARGET;" -c "CREATE DATABASE $TARGET;"

docker compose $ENVARG -f "$COMPOSE" exec -T postgres \
  pg_restore -U producthub -d "$TARGET" --no-owner --clean --if-exists < "$DUMP"

CNT=$(docker compose $ENVARG -f "$COMPOSE" exec -T postgres \
  psql -U producthub -d "$TARGET" -tAc "SELECT count(*) FROM sku;")
echo "[restore] 完成：$TARGET 的 sku 行数 = $CNT（与生产规模对照即验证备份可用）"
echo "[restore] 演练库核验后可删除： docker compose -f $COMPOSE exec -T postgres psql -U producthub -d postgres -c 'DROP DATABASE $TARGET;'"
