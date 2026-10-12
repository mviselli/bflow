@echo off
rem Starts BaggageFlow and opens it in the browser: double-click this file.
rem Press Ctrl+C (or close the window) to stop it.
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo BaggageFlow needs uv: https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)
uv run --locked baggageflow %*
if errorlevel 1 pause
