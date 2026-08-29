# Registers an hourly Windows scheduled task that mirrors the AgentOS audit
# anchor head to an off-host directory (ROADMAP item 3, transport step).
#
# Usage (from any PowerShell):
#   .\scripts\anchor-mirror-task.ps1 -Repo "D:\DeepSeek Harnes\AgentOS-main" `
#       -Db "D:\DeepSeek Harnes\AgentOS-main\.agentos-my" `
#       -Dest "D:\anchor-offsite"     # ideally another volume/synced folder
#
# The mirror command is idempotent: with an unchanged chain head it writes
# nothing new; every NEW state appends one immutable, content-addressed
# bundle plus a history line. Point -Dest at a git repo or a synced folder
# to get true off-host redundancy; optionally commit+push it on a schedule.
param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Db,
    [Parameter(Mandatory = $true)][string]$Dest,
    [string]$TaskName = "AgentOS anchor mirror"
)
$ErrorActionPreference = "Stop"
$agentos = Join-Path $Repo ".venv\Scripts\agentos.exe"
if (-not (Test-Path $agentos)) {
    throw "agentos not found at $agentos - run 'python -m venv .venv; .venv\Scripts\pip install -e .' in $Repo first"
}
$argument = "anchor-mirror --db `"$Db`" --dest `"$Dest`""
$action = New-ScheduledTaskAction -Execute $agentos -Argument $argument `
    -WorkingDirectory $Repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Description "AgentOS off-host audit anchor mirror (hourly, idempotent)" `
    -Force | Out-Null
Write-Host "Registered scheduled task '$TaskName' (hourly)."
Write-Host "Manual run:  `"$agentos`" anchor-mirror --db `"$Db`" --dest `"$Dest`""
