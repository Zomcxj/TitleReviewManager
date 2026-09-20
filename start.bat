@echo off
chcp 65001 >nul
cd /d "%~dp0"

cls
echo.
echo   ╔═══════════════════════════════════════════╗
echo   ║     职称评审管理系统 · 正在启动...       ║
echo   ╚═══════════════════════════════════════════╝
echo.

:: 定位 Python：优先 conda 环境 LLM，逐个探测常见安装位置。
:: 候选必须实际执行成功才算有效 —— 仅用 exist 判断会选中某些装了
:: 「应用执行别名」的占位 python.exe（存在但执行即失败）。
:: 注意：块内注释一律用 rem，不能用 ::（:: 在括号块内会被当作标签解析并报错）。
set "PYTHON="
for %%p in (
    "D:\Softwaredata\miniforge3\envs\llm\python.exe"
    "D:\JetBrains\Anaconda3\envs\LLM\python.exe"
    "C:\Users\%USERNAME%\miniconda3\envs\LLM\python.exe"
    "C:\Users\%USERNAME%\anaconda3\envs\LLM\python.exe"
    "D:\Anaconda3\envs\LLM\python.exe"
) do (
    if not defined PYTHON if exist %%p (
        "%%~p" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYTHON=%%~p"
    )
)
if not defined PYTHON (
    rem 回退到 PATH 中的 python（要求 3.10+）
    for /f "delims=" %%p in ('where python 2^>nul') do (
        if not defined PYTHON (
            "%%p" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
            if not errorlevel 1 set "PYTHON=%%p"
        )
    )
)
if not defined PYTHON (
    echo   ✗ 未找到可用的 Python（需 3.10+）。请安装 Python 或 conda 环境 LLM。
    pause
    exit /b 1
)
:: 依赖安装用 `python -m pip`：不推导 pip.exe 路径。
:: %%~dp 对文件路径返回的是所在目录，拼 `\pip.exe` 会得到错误路径
:: （实测 D:\...\envs\llm\python.exe → D:\pip.exe），因此不再单独维护 PIP 变量。

:: Detect LAN IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set "LAN_IP=%%a"
    goto :ip_found
)
:ip_found
set "LAN_IP=%LAN_IP: =%"
if "%LAN_IP%"=="" set "LAN_IP=localhost"

echo   [1/5] 安装后端依赖...
"%PYTHON%" -m pip install -q -r backend\requirements.txt 2>nul

echo   [2/5] 引导数据库（Alembic 迁移）...
cd backend
"%PYTHON%" db_bootstrap.py
if errorlevel 1 (
    echo.
    echo   ✗ 数据库迁移失败，启动中止。请检查上面的错误信息。
    cd ..
    pause
    exit /b 1
)
cd ..

echo   [3/5] 检查前端构建产物...
where node >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ✗ 未找到 Node.js，无法构建前端。
    echo     请安装 Node.js 18+ 后重试；或手动执行: cd frontend ^&^& npm install ^&^& npm run build
    pause
    exit /b 1
)
node frontend\scripts\ensure-build.mjs
if errorlevel 1 (
    echo   ✗ 前端构建失败，启动中止。
    pause
    exit /b 1
)

echo   [4/5] 填充种子数据...
cd backend && "%PYTHON%" seed.py >nul 2>&1 && cd ..

echo   [5/5] 启动服务...
echo   使用 Python: %PYTHON%
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