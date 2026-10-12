@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM 用 pythonw 启动，不显示控制台窗口
start "" pythonw launcher.py

REM 如果 pythonw 不可用，回退到 python
if errorlevel 1 (
    python launcher.py
)
