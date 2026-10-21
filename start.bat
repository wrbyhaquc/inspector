@echo off
rem Inspector UI: opens http://127.0.0.1:8765 in the browser. Close this window to stop the UI.
cd /d %~dp0
set PYTHONIOENCODING=utf-8
if not exist web\dist\index.html (
  echo First run: building the web UI...
  pushd web
  call npm install
  call npm run build
  popd
)
python -m server
pause
