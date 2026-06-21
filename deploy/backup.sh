#!/bin/sh
# 每日备份：pg_dump 自定义格式 → /opt/producthub/backups。支持多库（双租户内测）。
# 增强：失败/异常即告警、成功写心跳、大小骤降预警、GFS 保留（日30/周12/月12）。
# 可用环境变量覆盖（默认=生产单库行为）：
#   COMPOSE   compose 文件（默认 docker-compose.prod.yml；内测用 docker-compose.beta.yml）
#   ENV_FILE  传给 docker compose 的 --env-file（beta 栈需 deploy/.env.prod）
#   DBS       空格分隔的库名（默认 "producthub"；双租户设 "producthub producthub_b"）
#   WEBHOOK_URL  设了即推送钉钉/企微/飞书机器人；未设则仅写日志
# 安装（双租户内测）：crontab -e 加入
#   30 2 * * * COMPOSE=/opt/producthub/deploy/docker-compose.beta.yml ENV_FILE=/opt/producthub/deploy/.env.prod DBS="producthub producthub_b" /opt/producthub/deploy/backup.sh >> /opt/producthub/backups/backup.log 2>&1
# 备份不验证恢复 = 没有备份：每月跑一次 deploy/restore.sh 恢复演练（见 docs/数据安全与灾备策略.md）。
set -u

BACKUP_DIR=/opt/producthub/backups
COMPOSE="${COMPOSE:-/opt/producthub/deploy/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-}"
DBS="${DBS:-producthub}"
STAMP=$(date +%Y%m%d-%H%M%S)
DOW=$(date +%u)       # 1-7，7=周日
DOM=$(date +%d)       # 01-31
HEARTBEAT="$BACKUP_DIR/.last-success"
mkdir -p "$BACKUP_DIR" "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly"

ENVARG=""; [ -n "$ENV_FILE" ] && ENVARG="--env-file $ENV_FILE"

# 告警通道密钥从 600 权限的 .ops.env 读（PUSHPLUS_TOKEN / WEBHOOK_URL），不入仓、不进 crontab
[ -f /opt/producthub/deploy/.ops.env ] && . /opt/producthub/deploy/.ops.env

notify() {  # $1=级别 $2=消息
    echo "[$STAMP] [$1] $2"
    _msg="ProductHub 备份[$1] $STAMP: $2"
    if [ -n "${PUSHPLUS_TOKEN:-}" ]; then
        # PushPlus：推个人微信，template=txt 纯文本
        curl -fsS -m 10 -X POST https://www.pushplus.plus/send \
          -H 'Content-Type: application/json' \
          -d "{\"token\":\"${PUSHPLUS_TOKEN}\",\"title\":\"ProductHub 备份[$1]\",\"content\":\"${_msg}\",\"template\":\"txt\"}" \
          >/dev/null 2>&1 || true
    elif [ -n "${WEBHOOK_URL:-}" ]; then
        # 企业微信/钉钉群机器人格式（备选）
        curl -fsS -m 10 -X POST "$WEBHOOK_URL" \
          -H 'Content-Type: application/json' \
          -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"${_msg}\"}}" \
          >/dev/null 2>&1 || true
    fi
}
fail() { notify "FAIL" "$1"; exit 1; }

# 逐库备份（任一失败即整体告警退出，不写心跳——确保"半个系统没备份"会被发现）
for DB in $DBS; do
    DEST="$BACKUP_DIR/$DB-$STAMP.dump"
    if ! docker compose $ENVARG -f "$COMPOSE" exec -T postgres \
         pg_dump -U producthub -d "$DB" --format=custom > "$DEST" 2>/tmp/pgdump.err; then
        fail "$DB pg_dump 失败: $(head -c 300 /tmp/pgdump.err)"
    fi
    # 大小健全性：空文件即失败；较该库上次骤降>50% 预警
    SIZE=$(wc -c < "$DEST")
    [ "$SIZE" -gt 0 ] || fail "$DB 备份文件为空，疑似失败"
    PREV=$(ls -1t "$BACKUP_DIR/$DB"-*.dump 2>/dev/null | sed -n 2p)
    if [ -n "$PREV" ]; then
        PSIZE=$(wc -c < "$PREV")
        if [ "$PSIZE" -gt 0 ] && [ "$SIZE" -lt $((PSIZE / 2)) ]; then
            notify "WARN" "$DB 备份体积骤降：本次 $SIZE B，上次 $PSIZE B（请核查是否数据异常/截断）"
        fi
    fi
    # GFS：周日存周备份、每月 1 号存月备份
    [ "$DOW" = "7" ] && cp "$DEST" "$BACKUP_DIR/weekly/$DB-$STAMP.dump"
    [ "$DOM" = "01" ] && cp "$DEST" "$BACKUP_DIR/monthly/$DB-$STAMP.dump"
done

# 保留：日 30 天、周 84 天、月 365 天（覆盖所有库的 dump）
find "$BACKUP_DIR" -maxdepth 1 -name '*.dump' -mtime +30 -delete
find "$BACKUP_DIR/weekly" -name '*.dump' -mtime +84 -delete
find "$BACKUP_DIR/monthly" -name '*.dump' -mtime +365 -delete

# 全部库成功才写心跳（供 backup-watchdog.sh / 外部监控判活：last-success 过旧即告警）
date +%s > "$HEARTBEAT"
notify "OK" "备份成功 [$DBS] @ $STAMP"
# 异地：成功后由 deploy/offsite-sync.sh 推送对象存储 + 客户本地机 customer-pull.ps1 拉取（均加密）。
