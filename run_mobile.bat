@echo off
REM Starts the Expo dev server for the React Native app. Scan the QR code with the Expo Go app (SDK 57).
cd /d "%~dp0mobile"
if not exist node_modules ( call npm install )
echo.
echo On the phone's login screen set BACKEND SERVER to http://YOUR-PC-IP:8000
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo    PC IP:%%a
echo.
call npx expo start --lan
pause
