# Registers (or removes) the Windows scheduled task that wakes this PC on run days and runs
# scripts/pc_wake.ps1. Only for running the stack on your own PC; a server doesn't need it.
# Leave the PC asleep, not shut down: Windows can wake a sleeping PC, not a powered-off one.
#   powershell -ExecutionPolicy Bypass -File scripts\pc_schedule.ps1              # install / update
#   powershell -ExecutionPolicy Bypass -File scripts\pc_schedule.ps1 -Uninstall   # remove
# The days and time should sit a few minutes before DAILY_RUN_CRON in .env (05:00 Sun/Tue/Thu/Sat).
param(
    [string[]]$Days = @("Sunday", "Tuesday", "Thursday", "Saturday"),
    [string]$At = "04:45",
    [string]$AwakeUntil = "14:00",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$name = "Enchanted Everyday wake"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Output "Removed the '$name' task."
    exit 0
}

$script = Join-Path $PSScriptRoot "pc_wake.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -AwakeUntil $AwakeUntil"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $At
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12) -MultipleInstances IgnoreNew
# Runs as you, only while you're signed in (sleep keeps you signed in), so no password is stored
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Wakes the PC for The Enchanted Everyday run and keeps it awake until $AwakeUntil" `
    -Force | Out-Null
$next = (Get-ScheduledTaskInfo -TaskName $name).NextRunTime
Write-Output "Installed '$name': $($Days -join ', ') at $At, awake until $AwakeUntil. Next run: $next"
