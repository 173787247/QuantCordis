$ErrorActionPreference='Continue'
$env:PYTHONIOENCODING='utf-8'
$env:QUANTCORDIS_STRATEGY_ROOT='C:\Users\rchua\Desktop\AIFullStackDevelopment\AIQuantitativeTrading\20260513\CASE-AI量化系统'
$py = (Get-Command python -EA SilentlyContinue).Source
Set-Location $PSScriptRoot
Write-Output ('ROOT=' + $env:QUANTCORDIS_STRATEGY_ROOT)
& $py _slip_sweep.py
