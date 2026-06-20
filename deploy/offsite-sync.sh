#!/bin/sh
# 异地加密同步：把本地备份推送到对象存储（阿里云 OSS/腾讯云 COS/AWS S3）。
# 加密由 rclone crypt 远端透明完成（密钥在 rclone.conf，chmod 600，永不入仓）——
# 备份含报价金额/客户名等商业敏感数据，落地与传输必须加密。
#
# 前置（一次性）：
#   1) 安装 rclone；2) rclone config 建两个远端：
#        objstore  = 你的对象存储（OSS/COS/S3，开版本化+生命周期）
#        crypt     = type=crypt, remote=objstore:producthub-backups, 设 password/password2
#   3) chmod 600 ~/.config/rclone/rclone.conf
# 安装 cron：  0 3 * * * /opt/producthub/deploy/offsite-sync.sh >> /opt/producthub/backups/offsite.log 2>&1
#   （排在 backup.sh 之后；3-2-1 的第 3 份异地副本）
set -u

BACKUP_DIR=/opt/producthub/backups
CRYPT_REMOTE=${CRYPT_REMOTE:-crypt:}     # rclone crypt 远端
STAMP=$(date +%Y%m%d-%H%M%S)

notify() {
    echo "[$STAMP] [$1] offsite: $2"
    [ -n "${WEBHOOK_URL:-}" ] && curl -fsS -m 10 -X POST "$WEBHOOK_URL" \
      -H 'Content-Type: application/json' \
      -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"ProductHub 异地同步[$1] $STAMP: $2\"}}" \
      >/dev/null 2>&1 || true
}

command -v rclone >/dev/null 2>&1 || { notify "FAIL" "未安装 rclone"; exit 1; }

# 推送（crypt 远端自动加密）；远端保留与本地一致由对象存储生命周期策略管理
if rclone copy "$BACKUP_DIR" "$CRYPT_REMOTE" \
     --include 'producthub-*.dump' --include 'weekly/**' --include 'monthly/**' \
     --transfers 2 --retries 3; then
    notify "OK" "异地同步完成 → $CRYPT_REMOTE"
else
    notify "FAIL" "rclone 推送失败，异地副本可能缺失"
    exit 1
fi
