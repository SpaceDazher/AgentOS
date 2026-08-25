param([int]$BudgetS = 420)
$ErrorActionPreference = 'Continue'
$wt = 'D:\Project\AgentOS-wt-slo'
$tk = "$wt\research\tickets\stage-1\SLOQUAL-001"
$rd = "$tk\raw\sloqual-rerun-20260824-execB"
$log = "$rd\_progress.log"
New-Item -ItemType Directory -Force -Path $rd | Out-Null
if (-not (Test-Path "$rd\environment-manifest.json")) {
  Copy-Item "$tk\raw\environment-manifest.json" "$rd\environment-manifest.json" -Force
}
$env:PYTHONPATH = "$wt\src"
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location $wt

$scenarios = @('cold_start','warm_steady_state','sustained_load','soak','burst','queue_backpressure','provider_full_outage','provider_degraded','worker_restart','scheduler_restart','full_restart','sqlite_lock_contention','disk_slow_saturation','db_growth','network_faults','revocation_under_load','recovery_after_failures')
$ov = @(
  '--override','warm_steady_state.duration_s=12',
  '--override','sustained_load.duration_s=45',
  '--override','soak.duration_s=45',
  '--override','soak.sample_interval_s=15',
  '--override','burst.phase_duration_s=6',
  '--override','burst.burst_duration_s=10',
  '--override','queue_backpressure.duration_s=20',
  '--override','provider_full_outage.duration_s=30',
  '--override','provider_full_outage.outage_start_s=8',
  '--override','provider_full_outage.outage_end_s=20',
  '--override','provider_degraded.duration_s=25',
  '--override','sqlite_lock_contention.duration_s=25',
  '--override','db_growth.insert_budget_s=30',
  '--override','db_growth.target_rows=200000',
  '--override','network_faults.duration_s=40',
  '--override','revocation_under_load.trials_per_seed_level=3'
)

$exhausted = @{}
if (Test-Path $log) {
  foreach ($line in (Get-Content $log)) {
    if ($line -match '^FAILED seed=(\d+) (\S+) exit=') {
      $k = '{0}:{1}' -f $Matches[1], $Matches[2]
      $exhausted[$k] = [int]$exhausted[$k] + 1
    }
  }
}

$deadline = (Get-Date).AddSeconds($BudgetS)
$stopped = $false
$ran = 0
$anomalies = @()
foreach ($seed in @(11,22,33,44,55)) {
  foreach ($sc in $scenarios) {
    if ((Get-Date) -ge $deadline) { $stopped = $true; break }
    $out = "$rd\$sc\seed-$seed.json"
    if (Test-Path $out) { continue }
    if ([int]$exhausted[('{0}:{1}' -f $seed,$sc)] -ge 2) { continue }
    for ($attempt = 1; $attempt -le 2; $attempt++) {
      Add-Content -Path $log -Value ('{0:HH:mm:ss} seed={1} {2}' -f (Get-Date), $seed, $sc)
      $rl = Join-Path $rd ('_runner_{0}_{1}_a{2}.txt' -f $seed, $sc, $attempt)
      & python -m agentos.sloqual.runner run-scenario --ticket $tk --repo-src "$wt\src" --work-root "$tk\raw" --run-id sloqual-rerun-20260824-execB --scenario $sc --seed $seed @ov *> $rl
      $code = $LASTEXITCODE
      $ran++
      if (($code -eq 0) -and (Test-Path $out)) { break }
      if ($code -ne 0) {
        Add-Content -Path $log -Value ('FAILED seed={0} {1} exit={2}' -f $seed, $sc, $code)
      } else {
        $anomalies += ('exit0-no-file {0}:{1} a{2}' -f $seed, $sc, $attempt)
      }
    }
  }
  if ($stopped) { break }
}

$total = 0
$bad = @()
Get-ChildItem -Path $rd -Recurse -Filter 'seed-*.json' -File | ForEach-Object {
  $total++
  try { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null } catch { $bad += $_.FullName.Replace("$rd\", '') }
}
$pending = @()
foreach ($seed in @(11,22,33,44,55)) {
  foreach ($sc in $scenarios) {
    if (-not (Test-Path "$rd\$sc\seed-$seed.json")) { $pending += ('{0}:{1}' -f $sc, $seed) }
  }
}
Write-Output ('STOPPED_BY_BUDGET={0} RAN={1} TOTAL_JSON={2} BAD_JSON=[{3}] ANOMALIES=[{4}]' -f $stopped, $ran, $total, ($bad -join ' '), ($anomalies -join ' '))
Write-Output ('PENDING_COUNT={0}' -f $pending.Count)
Write-Output ('PENDING={0}' -f ($pending -join ','))
