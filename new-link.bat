@echo off
chcp 65001 >nul 2>&1
title 生成新的远程登录链接

cd /d "%~dp0"

echo 正在生成新的远程登录链接...
echo.

for /f "delims=" %%i in ('curl -s http://localhost:58231/admin/new-link') do set RESPONSE=%%i

if "%RESPONSE%"=="" (
    echo [错误] 无法连接到服务，请先运行 start.bat 启动服务
    pause
    exit /b 1
)

echo %RESPONSE% | python -c "import sys,json; d=json.load(sys.stdin); print('链接:', d['link']); print('有效期:', d['expires_minutes'], '分钟'); print('二维码:', d.get('qrcode','未生成'))"

echo.
pause
