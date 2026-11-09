$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython)) { throw 'Run .\setup.ps1 first.' }
& $VenvPython -m streamlit run frontend\app.py
