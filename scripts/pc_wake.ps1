# Run-day helper for running the stack on a Windows PC instead of a server.
# The scheduled task from scripts/pc_schedule.ps1 runs this when it wakes the PC from sleep on a
# run day and whenever you sign in (after a shutdown, the worker then catches up on a missed run). It starts
# Docker Desktop if it isn't running, brings the stack up, and keeps the PC from going back to sleep
# until -AwakeUntil, so /produce, /reshoot and Approve still work from your phone. After that,
# Windows is free to sleep again. The screen may turn off; only the system is kept awake.
#   powershell -ExecutionPolicy Bypass -File scripts\pc_wake.ps1 [-AwakeUntil 14:00]
param(
    [string]$AwakeUntil = "14:00",
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot)
)
# Not "Stop": Windows PowerShell turns docker's progress output on stderr into errors.
# Failures are checked through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"

$logDir = Join-Path $ProjectDir "work"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "pc_wake.log"
function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Output $line
}

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED: no idle sleep while this process runs; cleared when it exits
Add-Type -Namespace Win32 -Name Power -MemberDefinition @"
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
"@
[void][Win32.Power]::SetThreadExecutionState([uint32]"0x80000001")

$dockerHome = @(
    "$env:LOCALAPPDATA\Programs\DockerDesktop",
    "$env:ProgramFiles\Docker\Docker"
) | Where-Object { Test-Path (Join-Path $_ "Docker Desktop.exe") } | Select-Object -First 1
if (-not $dockerHome) { Log "Docker Desktop not found"; exit 1 }
$docker = Join-Path $dockerHome "resources\bin\docker.exe"

function DockerUp {
    & $docker info --format "{{.ServerVersion}}" *> $null
    return ($LASTEXITCODE -eq 0)
}

Log "started; keeping the PC awake until $AwakeUntil"
if (-not (DockerUp)) {
    Log "starting Docker Desktop"
    Start-Process (Join-Path $dockerHome "Docker Desktop.exe")
    $deadline = (Get-Date).AddMinutes(5)
    while (-not (DockerUp)) {
        if ((Get-Date) -gt $deadline) { Log "Docker didn't start within 5 minutes"; exit 1 }
        Start-Sleep -Seconds 5
    }
}

# Containers restart on their own once Docker is up; `up -d` also starts any that were stopped
& $docker compose --project-directory $ProjectDir up -d 2>&1 | ForEach-Object { Log "$_" }
if ($LASTEXITCODE -ne 0) { Log "docker compose up failed"; exit 1 }
Log "stack is up"

$until = [datetime]::ParseExact($AwakeUntil, "HH:mm", $null)
while ((Get-Date) -lt $until) { Start-Sleep -Seconds 60 }
Log "done; the PC may sleep again"
