# ARES Predator - Configuração do Task Scheduler no Windows
# Execute este script uma única vez como Administrador no PowerShell.
# Ele cria duas tarefas: sync rápido de dia (15 min) e lento de noite (90 min).

$pythonPath = (Get-Command python).Source
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$batFile    = Join-Path $scriptDir "run-sync.bat"

Write-Host "Python: $pythonPath"
Write-Host "Script: $batFile"

# ─── Tarefa 1: Dia (07:00 – 20:59) — a cada 15 minutos ──────────────────────
$triggersDia = @()
foreach ($hora in 7..20) {
    foreach ($minuto in @(0, 15, 30, 45)) {
        $t = New-ScheduledTaskTrigger -Daily -At ("{0:D2}:{1:D2}" -f $hora, $minuto)
        $triggersDia += $t
    }
}

$actionDia = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batFile`"" `
    -WorkingDirectory $scriptDir

$settingsDia = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "ARES Sync - Dia (15min)" `
    -Trigger $triggersDia `
    -Action $actionDia `
    -Settings $settingsDia `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "✔  Tarefa 'ARES Sync - Dia (15min)' criada."

# ─── Tarefa 2: Noite/madrugada (21:00 – 06:59) — a cada 90 minutos ──────────
$triggersNoite = @()
foreach ($horario in @("21:00","22:30","00:00","01:30","03:00","04:30","06:00")) {
    $t = New-ScheduledTaskTrigger -Daily -At $horario
    $triggersNoite += $t
}

$actionNoite = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batFile`"" `
    -WorkingDirectory $scriptDir

$settingsNoite = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "ARES Sync - Noite (90min)" `
    -Trigger $triggersNoite `
    -Action $actionNoite `
    -Settings $settingsNoite `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "✔  Tarefa 'ARES Sync - Noite (90min)' criada."
Write-Host ""
Write-Host "Pronto! As tarefas foram registradas no Task Scheduler."
Write-Host "Para testar agora: Start-ScheduledTask 'ARES Sync - Dia (15min)'"
