# Registers (or removes) the Windows scheduled task that runs scripts/pc_wake.ps1: it wakes this PC
# on run days, and also runs whenever you sign in, so the stack starts after a shutdown or a restart
# too. A run missed while the PC was off is then caught up by the worker (`engine serve`).
# Only for running the stack on your own PC; a server doesn't need it.
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
$me = "$env:USERDOMAIN\$env:USERNAME"
$trigger = @(
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $At),
    (New-ScheduledTaskTrigger -AtLogOn -User $me)
)
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12) -MultipleInstances IgnoreNew
# Runs as you, only while you're signed in (sleep keeps you signed in), so no password is stored
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Wakes the PC for The Enchanted Everyday run and keeps it awake until $AwakeUntil" `
    -Force | Out-Null
$next = (Get-ScheduledTaskInfo -TaskName $name).NextRunTime
Write-Output "Installed '$name': $($Days -join ', ') at $At and at every sign-in, awake until $AwakeUntil. Next wake-up: $next"
