#!/bin/bash

# ====================================================
#  Title Review Manager - 启动脚本
#  访问地址: http://localhost:8000
# ====================================================

cd "$(dirname "$0")"

echo ""
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║     职称评审管理系统 · 正在启动...       ║"
echo "  ╚═══════════════════════════════════════════╝"
echo ""

# 定位 Python（原脚本在第 18 行就使用 $PYTHON，却在第 68 行才赋值 —— 变量为空，
# 命令退化成 "install -q -r ..."，依赖与迁移从未真正执行）
#
# 注意：候选必须实际执行一次才算有效。Windows 的
# AppData\Local\Microsoft\WindowsApps\python3 是个可执行但退出码 49 的占位存根，
# 仅用 `-x` 判断会选中它，之后所有 python 命令都会静默失败。
is_usable_python() {
    [ -n "$1" ] && [ -x "$1" ] || return 1
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' > /dev/null 2>&1
}

find_python() {
    # 项目约定的 conda 环境优先（避免撞上系统占位存根）
    for candidate in \
        /d/Softwaredata/miniforge3/envs/llm/python.exe \
        /d/JetBrains/Anaconda3/envs/LLM/python.exe \
        /c/Users/*/miniconda3/envs/LLM/python.exe \
        /c/Users/*/anaconda3/envs/LLM/python.exe \
        "$(command -v python3 2>/dev/null)" \
        "$(command -v python 2>/dev/null)"; do
        if is_usable_python "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON=$(find_python)
if [ -z "$PYTHON" ]; then
    echo "  ✗ 未找到 Python。请安装 Python 3.10+ 或 conda 环境 LLM。"
    exit 1
fi
PIP="$(dirname "$PYTHON")/pip"

# 1. Install backend dependencies
echo "  [1/5] 安装后端依赖..."
"$PIP" install -q -r backend/requirements.txt 2>/dev/null

# 2. Bootstrap database (Alembic migrations)
echo "  [2/5] 引导数据库（Alembic 迁移）..."
cd backend
if ! "$PYTHON" db_bootstrap.py; then
    echo "  ✗ 数据库迁移失败，启动中止。请检查上面的错误信息。"
    exit 1
fi
cd ..

# 3. Ensure frontend build (dist 不入版本控制，缺失时需现场构建)
echo "  [3/5] 检查前端构建产物..."
if ! command -v node > /dev/null 2>&1; then
    echo "  ✗ 未找到 Node.js，无法构建前端。"
    echo "    请安装 Node.js 18+ 后重试；或手动执行: cd frontend && npm install && npm run build"
    exit 1
fi
if ! node frontend/scripts/ensure-build.mjs; then
    echo "  ✗ 前端构建失败，启动中止。"
    exit 1
fi

# 4. Seed data
echo "  [4/5] 填充种子数据..."
cd backend && "$PYTHON" seed.py > /dev/null 2>&1
cd ..

# 5. Start backend server
echo "  [5/5] 启动服务..."
echo ""

# Detect LAN IP
LAN_IP=$(ipconfig 2>/dev/null | grep -A 1 "IPv4" | tail -1 | awk '{print $NF}' | tr -d '\r' || hostname -I | awk '{print $1}')
if [ -z "$LAN_IP" ]; then LAN_IP="localhost"; fi

echo "  ┌───────────────────────────────────────────────────┐"
echo "  │  本机访问: http://localhost:8000                  │"
echo "  │  局域网访问: http://${LAN_IP}:8000                │"
echo "  │  客户表单: http://${LAN_IP}:8000/apply            │"
echo "  └───────────────────────────────────────────────────┘"
echo ""
echo "  默认账号:"
echo "    管理员   admin   / admin123"
echo "    业务员   salesman1 / sales123"
echo "    审核员   reviewer1 / review123"
echo ""

# Kill existing process on port 8000
echo "  检查端口 8000..."
if command -v fuser > /dev/null 2>&1; then
    fuser -k 8000/tcp 2>/dev/null && echo "  已释放端口 8000" || true
elif command -v wmic > /dev/null 2>&1; then
    wmic process where "commandline like '%uvicorn% and %8000%'" delete > /dev/null 2>&1 && echo "  已释放端口 8000" || true
fi
sleep 1

echo "  使用 Python: $("$PYTHON" --version 2>&1)"

# Start uvicorn
cd backend
"$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
cd ..

sleep 2

# Check if server started
if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "  ✓ 服务启动成功"
    echo ""
    
    # Auto open browser (cross-platform)
    if command -v xdg-open > /dev/null 2>&1; then
        xdg-open http://localhost:8000
    elif command -v open > /dev/null 2>&1; then
        open http://localhost:8000
    elif command -v start > /dev/null 2>&1; then
        start http://localhost:8000
    fi
    
    echo "  按 Ctrl+C 停止服务"
    echo ""
    wait $SERVER_PID
else
    echo "  ✗ 服务启动失败，请检查端口 8000 是否被占用"
    exit 1
fi
