$ErrorActionPreference='Continue'
$env:PYTHONIOENCODING='utf-8'
$py = (Get-Command python -EA SilentlyContinue).Source
Set-Location $PSScriptRoot
$log = Join-Path $env:TEMP 'qc_fetch_sample.log'
& $py tools\fetch_sample.py --step 5 *> $log
Write-Output ('exit=' + $LASTEXITCODE)
