# 客户办公机本地同步：从对象存储拉取【已加密】的备份副本到本地，作为 3-2-1 的"自己手里的一份"。
# 即便云账号/厂商出问题，客户本地仍有数据；拉下来的是加密 blob，解密需另行保管的 crypt 密钥（在公司侧），
# 故客户本地副本即使被他人接触也不泄露——安全与"数据在自己手里"兼得。
#
# 前置（一次性，在客户机）：
#   1) 装 rclone（https://rclone.org/downloads/）；
#   2) rclone config 建只读访问对象存储的远端 objstore（用一对【只读】子账号密钥，最小权限）；
#   3) 本脚本拉【原始加密对象】(objstore:)，不配 crypt，故客户机不持解密能力。
#   4) 用 Windows 任务计划程序每日触发：
#      程序：powershell.exe
#      参数：-NoProfile -ExecutionPolicy Bypass -File "C:\producthub-backup\customer-pull.ps1"
#
# 恢复（需要时，由公司侧用 crypt 密钥）：rclone copy crypt: <目标> 后 pg_restore。

$ErrorActionPreference = 'Stop'
$Remote = 'objstore:producthub-backups'         # 原始加密对象（文件名也被 crypt 加密）
$Local  = 'C:\producthub-backup'                 # 客户机本地落地目录
$LogFile = Join-Path $Local 'pull.log'

New-Item -ItemType Directory -Force -Path $Local | Out-Null

function Write-Log($level, $msg) {
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $level, $msg
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Output $line
}

try {
    if (-not (Get-Command rclone -ErrorAction SilentlyContinue)) {
        Write-Log 'FAIL' 'rclone 未安装，请先安装并 rclone config 配好 objstore 远端'
        exit 1
    }
    # 镜像拉取（含周/月目录）；--immutable 防止本地已有副本被远端改写覆盖
    rclone copy $Remote $Local --transfers 2 --retries 3 --log-level INFO
    if ($LASTEXITCODE -ne 0) { Write-Log 'FAIL' "rclone 拉取失败 exit=$LASTEXITCODE"; exit 1 }

    $files = Get-ChildItem -Path $Local -Recurse -File | Where-Object { $_.Name -notlike '*.log' }
    $count = $files.Count
    $newest = ($files | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    Write-Log 'OK' "本地副本文件数=$count，最新=$newest"
}
catch {
    Write-Log 'FAIL' $_.Exception.Message
    exit 1
}
