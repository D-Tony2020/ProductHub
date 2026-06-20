#!/bin/sh
# 每日备份：pg_dump 自定义格式 → /opt/producthub/backups。
# 增强：失败/异常即告警、成功写心跳、大小骤降预警、GFS 保留（日30/周12/月12）。
# 安装：crontab -e 加入
#   30 2 * * * /opt/producthub/deploy/backup.sh >> /opt/producthub/backups/backup.log 2>&1
# 告警：设 WEBHOOK_URL 环境变量（如企业微信/钉钉/飞书机器人）即推送；未设则仅写日志。
# 备份不验证恢复 = 没有备份：每月跑一次 deploy/restore.sh 恢复演练（见 docs/数据安全与灾备策略.md）。
set -u

BACKUP_DIR=/opt/producthub/backups
COMPOSE=/opt/producthub/deploy/docker-compose.prod.yml
STAMP=$(date +%Y%m%d-%H%M%S)
DOW=$(date +%u)       # 1-7，7=周日
DOM=$(date +%d)       # 01-31
DEST="$BACKUP_DIR/producthub-$STAMP.dump"
HEARTBEAT="$BACKUP_DIR/.last-success"
mkdir -p "$BACKUP_DIR" "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly"

notify() {  # $1=级别 $2=消息
    echo "[$STAMP] [$1] $2"
    [ -n "${WEBHOOK_URL:-}" ] && \
      curl -fsS -m 10 -X POST "$WEBHOOK_URL" \
        -H 'Content-Type: application/json' \
        -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"ProductHub 备份[$1] $STAMP: $2\"}}" \
        >/dev/null 2>&1 || true
}

fail() { notify "FAIL" "$1"; exit 1; }

# 1) 备份（失败即告警退出）
if ! docker compose -f "$COMPOSE" exec -T postgres \
     pg_dump -U producthub -d producthub --format=custom > "$DEST" 2>/tmp/pgdump.err; then
    fail "pg_dump 失败: $(head -c 300 /tmp/pgdump.err)"
fi

# 2) 大小健全性：空文件即失败；较上次骤降>50% 预警（可能截断/数据异常）
SIZE=$(wc -c < "$DEST")
[ "$SIZE" -gt 0 ] || fail "备份文件为空，疑似失败"
PREV=$(ls -1t "$BACKUP_DIR"/producthub-*.dump 2>/dev/null | sed -n 2p)
if [ -n "$PREV" ]; then
    PSIZE=$(wc -c < "$PREV")
    if [ "$PSIZE" -gt 0 ] && [ "$SIZE" -lt $((PSIZE / 2)) ]; then
        notify "WARN" "备份体积骤降：本次 $SIZE B，上次 $PSIZE B（请核查是否数据异常/截断）"
    fi
fi

# 3) GFS：周日存周备份、每月 1 号存月备份
[ "$DOW" = "7" ] && cp "$DEST" "$BACKUP_DIR/weekly/producthub-$STAMP.dump"
[ "$DOM" = "01" ] && cp "$DEST" "$BACKUP_DIR/monthly/producthub-$STAMP.dump"

# 4) 保留：日 30 天、周 12 周、月 12 月
find "$BACKUP_DIR" -maxdepth 1 -name 'producthub-*.dump' -mtime +30 -delete
find "$BACKUP_DIR/weekly" -name 'producthub-*.dump' -mtime +84 -delete
find "$BACKUP_DIR/monthly" -name 'producthub-*.dump' -mtime +365 -delete

# 5) 成功：写心跳（供外部监控判活：last-success 过旧即告警）
date +%s > "$HEARTBEAT"
notify "OK" "备份成功 $(ls -lh "$DEST" | awk '{print $5}')"
# 异地：备份成功后由 deploy/offsite-sync.sh 推送对象存储 + 客户本地机 customer-pull.ps1 拉取（均加密）。
