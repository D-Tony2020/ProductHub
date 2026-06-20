#!/bin/sh
# 备份看门狗：检查"最近一次成功备份"心跳，过旧即告警。
# 兜住 backup.sh 内部告警覆盖不到的盲区——cron 整个没跑/主机时钟/磁盘满导致根本没产生备份。
# 装在【独立位置最好是另一台机或客户机】跑，避免与备份同生共死；至少本机 cron：
#   0 9 * * * /opt/producthub/deploy/backup-watchdog.sh >> /opt/producthub/backups/watchdog.log 2>&1
set -u

HEARTBEAT=${HEARTBEAT:-/opt/producthub/backups/.last-success}
MAX_AGE_H=${MAX_AGE_H:-26}        # 容忍上限（小时）：日备份 + 富余
NOW=$(date +%s)

notify() {
    echo "[$(date +%F\ %T)] [$1] watchdog: $2"
    [ -n "${WEBHOOK_URL:-}" ] && curl -fsS -m 10 -X POST "$WEBHOOK_URL" \
      -H 'Content-Type: application/json' \
      -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"ProductHub 备份看门狗[$1]: $2\"}}" \
      >/dev/null 2>&1 || true
}

if [ ! -f "$HEARTBEAT" ]; then
    notify "ALERT" "找不到备份心跳文件 $HEARTBEAT —— 备份可能从未成功运行"
    exit 1
fi

LAST=$(cat "$HEARTBEAT" 2>/dev/null || echo 0)
AGE_H=$(( (NOW - LAST) / 3600 ))
if [ "$AGE_H" -ge "$MAX_AGE_H" ]; then
    notify "ALERT" "最近一次成功备份已是 ${AGE_H} 小时前（阈值 ${MAX_AGE_H}h）—— 备份链可能已断！"
    exit 1
fi
echo "[$(date +%F\ %T)] [OK] watchdog: 最近备份 ${AGE_H}h 前，正常"
