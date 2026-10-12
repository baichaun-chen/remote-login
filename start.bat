@echo off
chcp 65001 >nul 2>&1
title 豆包远程登录服务

echo ============================================================
echo   豆包远程登录服务 - 启动中
echo ============================================================
echo.

cd /d "%~dp0"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查依赖
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [1/2] 正在安装依赖包...
    python -m pip install flask uiautomation pyautogui pillow requests qrcode -q
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
    echo [1/2] 依赖安装完成
) else (
    echo [1/2] 依赖已就绪
)

echo.
echo [2/2] 启动服务...
echo.
echo   提示：
echo   - 请确保桌面版豆包已打开并停留在登录页面
echo   - 启动后会显示远程登录链接和二维码
echo   - 按 Ctrl+C 可停止服务
echo.
echo ============================================================
echo.

python app.py

pause
