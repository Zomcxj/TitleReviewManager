# 职称服务内部管理平台

## 快速开始

### 1. 安装依赖

```bash
# 后端
cd backend
pip3 install -r requirements.txt --break-system-packages

# 前端
cd frontend
npm install
```

### 2. 启动服务

```bash
# 终端 1 - 启动后端
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# 终端 2 - 启动前端
cd frontend
npm run dev
```

### 3. 访问应用

- 前端：http://localhost:5173
- API: http://localhost:8000/api/health

### 4. 测试账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 业务员 | salesman1 | sales123 |
| 审核员 | reviewer1 | review123 |

## 技术栈

- **前端**: Vue 3 + TypeScript + Element Plus
- **后端**: FastAPI + SQLAlchemy + SQLite

## 文档

- [功能说明](docs/features.md)
- [API 文档](docs/api.md)
- [部署指南](docs/deployment.md)

## 许可证

MIT License
