$ErrorActionPreference='Continue'
$env:PYTHONIOENCODING='utf-8'
$env:QUANTCORDIS_STRATEGY_ROOT='C:\Users\rchua\Desktop\AIFullStackDevelopment\AIQuantitativeTrading\20260513\CASE-AI量化系统'
$py = (Get-Command python -EA SilentlyContinue).Source
Set-Location $PSScriptRoot
$log = Join-Path $env:TEMP 'qc_screen2.log'
& $py tools\strategy_screen.py --label full *> $log
Write-Output ('exit=' + $LASTEXITCODE)
