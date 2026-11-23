# Arranca NEXUS-IA y lo reinicia con backoff si se cae. Ctrl+C para detener.
# Uso (PowerShell, desde la raiz del proyecto):  .\start_bot.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "No encuentro el venv. Crea backend\.venv primero (ver README)."; exit 1 }

$logDir = Join-Path $backend "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$env:LOG_TO_FILE = "true"            # el logging a archivo enmascara secretos (ver app/logging_setup.py)
$env:PYTHONUTF8 = "1"

$delay = 5            # segundos
$maxDelay = 300
Set-Location $backend
while ($true) {
    $started = Get-Date
    Write-Host ("[{0}] Iniciando NEXUS-IA..." -f $started.ToString("HH:mm:ss"))
    & $py -m app.main
    $code = $LASTEXITCODE
    $ran = ((Get-Date) - $started).TotalSeconds
    if ($ran -gt 120) { $delay = 5 }      # corrio estable: reinicia el backoff
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path (Join-Path $logDir "supervisor.log") -Value "$stamp salida codigo=$code tras $([int]$ran)s; reinicio en ${delay}s"
    Write-Host "El bot se detuvo (codigo $code). Reinicio en $delay s... (Ctrl+C para salir)"
    Start-Sleep -Seconds $delay
    $delay = [Math]::Min($delay * 2, $maxDelay)
}
