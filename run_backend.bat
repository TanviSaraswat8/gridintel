@echo off
REM Starts the FastAPI backend + web dashboard on port 8000 (all network interfaces so the phone can connect).
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
if not exist models\substations.json (
  echo Models not found - building dataset and models from data\raw ...
  python scripts\build_pipeline.py
)
echo.
echo ==================================================================
echo  Landing page  :  http://localhost:8000
echo  Command Center:  http://localhost:8000/app
echo  API docs      :  http://localhost:8000/docs
echo  Phone (browser fallback) : http://YOUR-PC-IP:8000/mobile
echo  Your PC's IP address(es):
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo        %%a
echo  Demo login: operator / hvpnl2026
echo  If Windows Firewall asks, click "Allow access" (Private network).
echo ==================================================================
echo.
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
