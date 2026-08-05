@echo off
setlocal
cd /d "%~dp0"
title MorphoStack Dev

echo.
echo  MorphoStack dev launcher
echo  -------------------------
echo  Project: %CD%
echo.

if not exist ".venv\Scripts\morphostack.exe" (
  echo  ERROR: Project virtualenv not found.
  echo.
  echo  From this folder, run once in a terminal:
  echo    python -m venv .venv
  echo    .\.venv\Scripts\python -m pip install -e ".[all]"
  echo    .\.venv\Scripts\morphostack init --web
  echo.
  pause
  exit /b 1
)

echo  Starting API + Vite UI...
echo  UI:  http://127.0.0.1:5173
echo  API: http://127.0.0.1:8000
echo.
echo  Leave this window open while developing.
echo  Press Ctrl+C to stop both servers.
echo.

".venv\Scripts\morphostack.exe" dev
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo  Dev server stopped with exit code %EXIT_CODE%.
  pause
  exit /b %EXIT_CODE%
)

echo  Dev server stopped.
pause
exit /b 0
