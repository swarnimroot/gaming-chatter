# Nightly daily-pipeline trigger for Windows Task Scheduler.
#
# Invoked by scripts/daily_trigger.xml at 23:00 local. POSTs to the running
# gaming-chatter server's guarded trigger endpoint; the pipeline itself runs
# in-process (single-process constraint intact — this script is only the
# OS-level alarm clock). Task Scheduler is exempt from Modern Standby app
# suspension, which is why this fires reliably on an unattended laptop while
# the in-process APScheduler cron can be suspended past its fire time
# (observed 2026-06-11; see DECISIONS 2026-06-12).
#
# The endpoint routes through jobs.run_daily_pipeline_scheduled, which skips
# if a daily already started in the last 12h — so this poke and the in-app
# cron can never double-spend the same night.
#
# If the server is down, the POST fails and we log + exit 1; the app's
# startup catch-up self-heals the missed night on next boot.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $RepoRoot "data\trigger_log"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$Ts = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "trigger_$Ts.log"

$Url = "http://127.0.0.1:8001/runs/trigger-scheduled/daily"
try {
    $resp = Invoke-RestMethod -Method Post -Uri $Url -TimeoutSec 30
    "$(Get-Date -Format o) POST $Url -> $resp" | Out-File $LogFile -Encoding utf8
    exit 0
} catch {
    "$(Get-Date -Format o) POST $Url FAILED: $($_.Exception.Message)" | Out-File $LogFile -Encoding utf8
    exit 1
}
