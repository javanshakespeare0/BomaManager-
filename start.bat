@echo off
REM Activate venv (cmd) and run app
set APP_ENV=development
set SECRET_KEY=dev-secret-key
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    python app.py
) else (
    echo Virtual environment not found. Run the venv python directly:
    echo c:/Users/HI/OneDrive/Desktop/BomaManager/.venv/Scripts/python.exe app.py
)
