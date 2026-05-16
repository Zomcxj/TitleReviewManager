#!/bin/bash
set -e

echo "=== 职称服务内部管理平台 ==="

# Install backend dependencies
echo "[1/3] 安装后端依赖..."
pip install --break-system-packages -q -r backend/requirements.txt 2>/dev/null || pip install -q -r backend/requirements.txt

# Initialize database
echo "[2/3] 初始化数据库..."
cd backend && python seed.py && cd ..

# Start backend
echo "[3/3] 启动服务..."
echo "后端: http://localhost:8000"
echo "前端: http://localhost:5173"
echo "客户自助表单: http://localhost:5173/apply"
echo ""
echo "默认账号:"
echo "  管理员: admin / admin123"
echo "  业务员: salesman1 / sales123"
echo "  审核员: reviewer1 / review123"
echo ""

# Start backend in background
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# Start frontend
cd frontend && npm install && npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
