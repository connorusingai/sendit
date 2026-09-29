@echo off
echo Sendit is running at http://localhost:8000  (close this window to stop it)
start http://localhost:8000
cd /d %~dp0
py -m http.server 8000
