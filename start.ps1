# PowerShell script to activate venv and run app
$env:APP_ENV = 'development'
if (Test-Path -Path .\.venv\Scripts\Activate.ps1) {
    . .\.venv\Scripts\Activate.ps1
    python app.py
} else {
    Write-Host "Virtual environment not found. Run directly:" -ForegroundColor Yellow
    Write-Host "c:/Users/HI/OneDrive/Desktop/BomaManager/.venv/Scripts/python.exe app.py" -ForegroundColor Cyan
}
