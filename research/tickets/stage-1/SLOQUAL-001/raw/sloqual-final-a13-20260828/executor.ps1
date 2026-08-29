$qualRunId = "sloqual-final-a13-20260828"
$ErrorActionPreference = "Stop"

$qualRepo = "D:/Project/AgentOS-wt-stability"
$qualPython = "C:/Users/Daniil/AppData/Roaming/uv/python/cpython-3.11-windows-x86_64-none/python.exe"
$qualTicket = "research/tickets/stage-1/SLOQUAL-001"
$qualWorkRoot = "research/tickets/stage-1/SLOQUAL-001/raw"
$qualSeeds = @(11, 22, 33, 44, 55)
$qualScenarios = @(
    "cold_start", "warm_steady_state", "sustained_load", "soak", "burst",
    "queue_backpressure", "provider_full_outage", "provider_degraded",
    "worker_restart", "scheduler_restart", "full_restart",
    "sqlite_lock_contention", "disk_slow_saturation", "db_growth",
    "network_faults", "revocation_under_load", "recovery_after_failures"
)
$qualOverrides = @{
    sustained_load = @("sustained_load.duration_s=45")
    soak = @("soak.duration_s=45", "soak.sample_interval_s=15")
    burst = @("burst.phase_duration_s=6", "burst.burst_duration_s=10")
    queue_backpressure = @("queue_backpressure.duration_s=20")
    provider_full_outage = @("provider_full_outage.duration_s=30", "provider_full_outage.outage_start_s=8", "provider_full_outage.outage_end_s=20")
    provider_degraded = @("provider_degraded.duration_s=25")
    sqlite_lock_contention = @("sqlite_lock_contention.duration_s=25")
    db_growth = @("db_growth.insert_budget_s=30", "db_growth.target_rows=200000")
    network_faults = @("network_faults.duration_s=40")
    revocation_under_load = @("revocation_under_load.trials_per_seed_level=7")
}
Set-Location -LiteralPath $qualRepo
$env:PYTHONPATH = "src"
$qualRunRoot = Join-Path $qualWorkRoot $qualRunId
& $qualPython -m agentos.sloqual.runner env-manifest --ticket $qualTicket --repo-root . --work-root $qualWorkRoot --out (Join-Path $qualRunRoot "environment-manifest.json")
if ($LASTEXITCODE -ne 0) {
    throw "environment manifest failed: exit=$LASTEXITCODE"
}

foreach ($qualSeed in $qualSeeds) {
    foreach ($qualScenario in $qualScenarios) {
        $qualArgs = @(
            "-m", "agentos.sloqual.runner", "run-scenario",
            "--ticket", $qualTicket,
            "--repo-src", "src",
            "--work-root", $qualWorkRoot,
            "--run-id", $qualRunId,
            "--scenario", $qualScenario,
            "--seed", "$qualSeed"
        )
        foreach ($qualOverride in ($qualOverrides[$qualScenario] | Where-Object { $_ })) {
            $qualArgs += @("--override", $qualOverride)
        }
        & $qualPython @qualArgs
        if ($LASTEXITCODE -ne 0) {
            throw "scenario failed: $qualScenario seed=$qualSeed exit=$LASTEXITCODE"
        }
    }
}
