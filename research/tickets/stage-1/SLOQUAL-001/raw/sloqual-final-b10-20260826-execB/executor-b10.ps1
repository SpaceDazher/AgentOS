$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'D:/Project/AgentOS-wt-slo/src'
$ticket = 'D:/Project/AgentOS-wt-slo/research/tickets/stage-1/SLOQUAL-001'
$work = 'D:/Project/AgentOS-wt-slo/research/tickets/stage-1/SLOQUAL-001/raw'
$run = 'sloqual-final-b10-20260826-execB'
$src = 'D:/Project/AgentOS-wt-slo/src'
$scenarios = @(
    'cold_start', 'warm_steady_state', 'sustained_load', 'soak', 'burst',
    'queue_backpressure', 'provider_full_outage', 'provider_degraded',
    'worker_restart', 'scheduler_restart', 'full_restart',
    'sqlite_lock_contention', 'disk_slow_saturation', 'db_growth',
    'network_faults', 'revocation_under_load', 'recovery_after_failures'
)
$seeds = @(11, 22, 33, 44, 55)

foreach ($scenario in $scenarios) {
    foreach ($seed in $seeds) {
        $runArgs = @(
            '-m', 'agentos.sloqual.runner', 'run-scenario',
            '--ticket', $ticket, '--repo-src', $src, '--work-root', $work,
            '--run-id', $run, '--scenario', $scenario, '--seed', [string]$seed
        )
        switch ($scenario) {
            'sustained_load' {
                $runArgs += @('--override', 'sustained_load.duration_s=45')
            }
            'soak' {
                $runArgs += @('--override', 'soak.duration_s=45')
                $runArgs += @('--override', 'soak.sample_interval_s=15')
            }
            'burst' {
                $runArgs += @('--override', 'burst.phase_duration_s=6')
                $runArgs += @('--override', 'burst.burst_duration_s=10')
            }
            'queue_backpressure' {
                $runArgs += @('--override', 'queue_backpressure.duration_s=20')
            }
            'provider_full_outage' {
                $runArgs += @('--override', 'provider_full_outage.duration_s=30')
                $runArgs += @('--override', 'provider_full_outage.outage_start_s=8')
                $runArgs += @('--override', 'provider_full_outage.outage_end_s=20')
            }
            'provider_degraded' {
                $runArgs += @('--override', 'provider_degraded.duration_s=25')
            }
            'sqlite_lock_contention' {
                $runArgs += @('--override', 'sqlite_lock_contention.duration_s=25')
            }
            'db_growth' {
                $runArgs += @('--override', 'db_growth.insert_budget_s=30')
                $runArgs += @('--override', 'db_growth.target_rows=200000')
            }
            'network_faults' {
                $runArgs += @('--override', 'network_faults.duration_s=40')
            }
            'revocation_under_load' {
                $runArgs += @('--override', 'revocation_under_load.trials_per_seed_level=7')
            }
        }
        Write-Output ("RUN {0} seed {1}" -f $scenario, $seed)
        & python @runArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Error ("STOP nonzero exit {0} at {1} seed {2}" -f $LASTEXITCODE, $scenario, $seed)
            exit $LASTEXITCODE
        }
    }
}
Write-Output 'ALL 85 SCENARIOS COMPLETED'
