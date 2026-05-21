# 职称服务内部管理平台 (Title Review Manager)

企业内部职称申报材料审核与管理平台。支持 NAS 存储、多角色协作、批量导入导出。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Element Plus + Pinia + Vite |
| 后端 | Python 3.10 + FastAPI + SQLAlchemy + Pydantic v2 |
| 数据库 | SQLite (开发) / PostgreSQL (生产) |
| 存储 | 本地 / SMB NAS（可配置） |
| 部署 | Docker + docker-compose |

## 快速开始

### 开发环境

```bash
# 1. 安装后端依赖
cd backend
pip install -r requirements.txt

# 2. 初始化数据库（生成种子数据）
python seed.py

# 3. 启动后端
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 4. 安装前端依赖（另一个终端）
cd frontend
npm install

# 5. 启动前端
npm run dev
```

默认账号：`admin / admin123`

### Docker 部署

```bash
docker-compose up -d
```

## 项目结构

```
├── backend/
│   ├── routers/          # API 路由模块
│   │   ├── auth.py           # 认证 (JWT + Cookie)
│   │   ├── customers.py      # 客户 CRUD + 筛选
│   │   ├── applications.py   # 申报批次
│   │   ├── materials.py      # 材料上传/下载/浏览
│   │   ├── reviews.py        # 审核
│   │   ├── feedback.py       # 机构反馈
│   │   ├── users.py          # 用户管理（管理员）
│   │   ├── imports.py        # Excel 批量导入
│   │   ├── exports.py        # Excel 导出
│   │   ├── dashboard.py      # 工作台统计
│   │   ├── notifications.py  # 消息通知
│   │   └── ...
│   ├── models.py        # SQLAlchemy 模型
│   ├── schemas.py       # Pydantic 请求/响应模型
│   ├── auth.py          # JWT + 密码 + 限流
│   ├── storage.py       # 存储抽象层（本地/SMB NAS）
│   ├── database.py      # DB 连接（SQLite/PostgreSQL）
│   └── seed.py          # 种子数据
├── frontend/
│   └── src/
│       ├── views/           # 页面组件
│       ├── components/      # 复用组件
│       ├── stores/          # Pinia 状态
│       ├── api/             # Axios 实例
│       └── router/          # 路由配置
├── tests/
│   ├── test_storage.py    # 存储 + 材料 API 测试
│   └── test_users.py      # 用户管理 API 测试
├── Dockerfile
└── docker-compose.yml
```

## 核心功能

### 客户管理
- 客户创建/编辑/删除、身份证号查重
- 关键词/状态/负责人筛选
- 批量导入（Excel）、导出
- 公海池（领用/释放/超时回收）

### 材料管理
- 按类型分组上传，保留原始文件名
- 版本管理（上传同类型自动递增版本）
- 文件预览（图片/PDF）
- NAS 目录树浏览
- 审核状态标记

### 存储架构
```
customers/
  {year}/
    {salesman_username}/
      {customer_name}_{pinyin_initial}/
        1-身份证明/
          id_front.pdf
          id_back.pdf
        2-学历学位/
          degree.pdf
        3-职称证书/
          ...
```

- **目录模板**：`customers/{year}/{salesman}/{customer_name}_{pinyin}/{category_number}-{category_name}/{filename}`
- **存储后端**：通过 `STORAGE_BACKEND=local|smb` 环境变量配置
- **NAS**：预设适用于 Synology/QNAP 的 SMB 路径模板
- **文件审计**：所有文件操作记录到 `file_audit.log`

### 审核工作流
```
初次申报 → 完成资料 → 提交评审机构审核 → [返修 | 通过 | 不通过]
               ↑              ↓
            资料补充 ←── 二次申报 ←── 不通过
```

### 用户角色
| 角色 | 权限 |
|------|------|
| 管理员 | 全部权限 + 用户管理 + 审计日志 |
| 业务员 | 客户/材料管理、导入导出、公海池 |
| 审核员 | 审核工作台、材料查看/下载 |

## 配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DATABASE_URL` | `sqlite:///./title_service.db` | 数据库连接 |
| `JWT_SECRET_KEY` | 自动生成 | JWT 签名密钥 |
| `STORAGE_BACKEND` | `local` | 存储后端：local / smb |
| `NAS_ROOT` | `./nas_storage` | NAS 挂载/存储根目录 |
| `SMB_USER` | - | SMB 用户名 |
| `SMB_PASS` | - | SMB 密码 |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS 白名单 |
