Set-Location -LiteralPath $PSScriptRoot
$env:APP_ENV = 'development'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Virtual environment not found. Create it with: python -m venv .venv"
    exit 1
}
& $python app.py
