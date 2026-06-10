#!/bin/sh
# 每日备份：pg_dump 到 /opt/producthub/backups，保留 30 天。
# 安装：crontab -e 加入
#   30 2 * * * /opt/producthub/deploy/backup.sh >> /opt/producthub/backups/backup.log 2>&1
# 备份不验证恢复等于没有备份：每月在测试库执行一次恢复演练（见 README 运维章节）。
set -eu

BACKUP_DIR=/opt/producthub/backups
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"

docker compose -f /opt/producthub/deploy/docker-compose.prod.yml exec -T postgres \
  pg_dump -U producthub -d producthub --format=custom \
  > "$BACKUP_DIR/producthub-$STAMP.dump"

# 保留 30 天
find "$BACKUP_DIR" -name 'producthub-*.dump' -mtime +30 -delete

echo "[$STAMP] backup ok: $(ls -lh "$BACKUP_DIR/producthub-$STAMP.dump" | awk '{print $5}')"
# 异地留存：客户办公电脑用 WinSCP/计划任务定期拉取该目录（交付时配置）
