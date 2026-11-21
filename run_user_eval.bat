@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python.
    echo Hay cai Python 3.11+ va them vao PATH, hoac tao .venv trong thu muc du an.
    echo.
    pause
    exit /b 1
)

if not exist "data\user_images" (
    echo [LOI] Khong tim thay thu muc data\user_images.
    pause
    exit /b 1
)

if not exist "data\user_labels.csv" (
    echo [LOI] Khong tim thay file data\user_labels.csv.
    pause
    exit /b 1
)

set "LABEL_LINES=0"
for /f %%A in ('find /c /v "" ^< "data\user_labels.csv"') do set "LABEL_LINES=%%A"
if %LABEL_LINES% LSS 2 (
    echo [THONG BAO] File data\user_labels.csv moi chi co dong tieu de.
    echo Hay them it nhat mot dong nhan cho moi anh trong data\user_images.
    echo Xem huong dan trong data\user_images\README.md.
    echo.
    pause
    exit /b 1
)

echo Dang danh gia anh trong data\user_images ...
"%PYTHON%" main.py evaluate --labels data\user_labels.csv --samples-dir data\user_images --split all --output-csv results\user_evaluation.csv --summary-json results\user_summary.json --summary-md results\user_summary.md
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo [LOI] Danh gia that bai voi ma %EXIT_CODE%.
) else (
    echo Da xong. Xem ket qua trong thu muc results.
)
echo.
pause
exit /b %EXIT_CODE%
