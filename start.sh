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

# 1. Install backend dependencies
echo "  [1/3] 安装后端依赖..."
$PIP install -q -r backend/requirements.txt 2>/dev/null

# 2. Initialize database
echo "  [2/3] 初始化数据库..."
cd backend && $PYTHON seed.py > /dev/null 2>&1
cd ..

# 3. Start backend server
echo "  [3/3] 启动服务..."
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

# Find conda env python (3.10.16 required for list[str] type hints)
conda_python=$(ls -d /d/JetBrains/Anaconda3/envs/LLM/python.exe /c/Users/*/AppData/Local/miniconda3/envs/LLM/python.exe 2>/dev/null | head -1)
if [ -z "$conda_python" ]; then
    conda_python="python"
fi
PYTHON=$conda_python
PIP=$(dirname "$conda_python")/pip.exe
echo "  使用 Python: $($PYTHON --version 2>&1)"

# Start uvicorn
cd backend
$conda_python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
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
