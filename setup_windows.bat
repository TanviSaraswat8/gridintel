@echo off
REM One-time setup on Windows: Python virtual environment + backend packages + mobile packages.
cd /d "%~dp0"
echo === Creating Python virtual environment (.venv) ===
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if errorlevel 1 ( echo Python 3.10+ is required. Install from python.org and tick "Add to PATH". & pause & exit /b 1 )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 ( echo pip install failed & pause & exit /b 1 )

echo.
echo === Installing mobile app packages (needs Node.js 20+) ===
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js not found - skipping mobile install. The phone can still use http://YOUR-PC-IP:8000/mobile
) else (
  pushd mobile
  call npm install
  popd
)
echo.
echo Setup complete. Next: run_backend.bat
pause
