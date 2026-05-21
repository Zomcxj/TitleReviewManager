@echo off
chcp 65001 >nul
cd /d "%~dp0"

cls
echo.
echo   ╔═══════════════════════════════════════════╗
echo   ║     职称评审管理系统 · 正在启动...       ║
echo   ╚═══════════════════════════════════════════╝
echo.

set "PYTHON=D:\JetBrains\Anaconda3\envs\LLM\python.exe"
set "PIP=D:\JetBrains\Anaconda3\envs\LLM\Scripts\pip.exe"

:: Detect LAN IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set "LAN_IP=%%a"
    goto :ip_found
)
:ip_found
set "LAN_IP=%LAN_IP: =%"
if "%LAN_IP%"=="" set "LAN_IP=localhost"

echo   [1/3] 安装后端依赖...
"%PIP%" install -q -r backend\requirements.txt 2>nul

echo   [2/3] 初始化数据库...
cd backend && "%PYTHON%" seed.py >nul 2>&1 && cd ..

echo   [3/3] 启动服务...
echo   使用 Python: 3.10.16 (LLM)
echo.
echo   ┌───────────────────────────────────────────────────┐
echo   │  本机访问: http://localhost:8000                  │
echo   │  局域网访问: http://%LAN_IP%:8000                 │
echo   │  客户表单: http://%LAN_IP%:8000/apply             │
echo   └───────────────────────────────────────────────────┘
echo.
echo   默认账号:
echo     管理员   admin   / admin123
echo     业务员   salesman1 / sales123
echo     审核员   reviewer1 / review123
echo.

:: Check and kill existing process on port 8000
echo   检查端口 8000...
for /f "tokens=1-5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    echo   发现占用进程 PID=%%e，正在终止...
    taskkill /F /PID %%e >nul 2>&1
    echo   已释放端口 8000
)
timeout /t 1 /nobreak >nul

:: Start server and open browser
cd backend
start /B "TitleReview" "%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8000
cd ..

timeout /t 3 /nobreak >nul
start http://localhost:8000

echo   ✓ 服务已启动，请在浏览器中访问
echo   按任意键停止服务...
pause >nul

:: Cleanup
taskkill /F /IM python.exe /FI "COMMANDLINE eq uvicorn" >nul 2>&1
echo 服务已停止。