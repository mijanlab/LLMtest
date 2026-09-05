@echo off
title LLM Speed & Latency Benchmark
where py >nul 2>&1
if errorlevel 1 (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python was not found. Install Python 3.8+ and try again.
    pause
    exit /b 1
  )
  set PY_CMD=python
) else (
  set PY_CMD=py
)

%PY_CMD% tui.py
pause

