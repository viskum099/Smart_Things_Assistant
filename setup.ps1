$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python 3.11 or newer is required. Install Python and reopen PowerShell.'
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.venv\Scripts\python.exe'))) {
    python -m venv (Join-Path $ProjectRoot '.venv')
}

$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')
& $VenvPython (Join-Path $ProjectRoot 'data\validate_sic_dataset.py')
Write-Host 'Smart_Things_Assistant setup complete. Run .\run_api.ps1 and .\run_ui.ps1 in separate PowerShell windows.'
