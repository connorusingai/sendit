@echo off
echo Stomped is running at http://localhost:8000  (close this window to stop it)
cd /d %~dp0
rem Open the browser 2 seconds after the server starts, so the page is ready when it loads
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8000"
py -m http.server 8000
