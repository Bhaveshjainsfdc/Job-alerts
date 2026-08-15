<#
Removes the scheduled task created by setup.ps1. This does not delete this
folder or your config.json - it just stops the automatic checking.
#>

$taskName = "AmazonWarehouseJobAlert"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task '$taskName'. Automatic checking is now stopped." -ForegroundColor Green
} else {
    Write-Host "No scheduled task named '$taskName' was found - nothing to do."
}
