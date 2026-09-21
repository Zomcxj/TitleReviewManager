# TitleReviewManager — 项目指令

## 通用规则

- 每次回复开头必须说 **"收到！！！老大！！！"**
- **不要主动执行 git commit/push**，所有提交必须等用户明确批准

## 项目结构

```
backend/        — FastAPI + SQLAlchemy + Pydantic v2 后端
  main.py       — FastAPI 入口，手动注册所有 router
  routers/      — API 路由模块（auth, customers, applications, materials, reviews 等）
  models.py     — SQLAlchemy ORM 模型
  schemas.py    — Pydantic 请求/响应模型
  enums.py      — 集中枚举（角色、状态、类别、配置常量）
  auth.py       — JWT（Cookie + Bearer）、bcrypt、登录限流/锁定
  storage.py    — 存储抽象层（local / SMB NAS），文件审计日志
  database.py   — DB 连接（SQLite 开发 / PostgreSQL 生产）
  seed.py       — 种子数据
  tasks/        — SLA 定时任务
  utils/        — audit_logger（操作审计装饰器）
frontend/       — Vue 3 + TypeScript + Element Plus + Pinia + Vite
  src/
    api/index.ts       — Axios 实例
    router/index.ts    — 路由配置
    stores/auth.ts     — Pinia 认证状态
    views/             — 页面组件
    components/        — 复用组件
docs/           — 文档（api.md, deployment.md, features.md）
```

## Python 环境

后端运行在名为 `LLM` 的 Anaconda 环境中。

- **Python 路径**: `D:\Softwaredata\miniforge3\envs\llm\python.exe`
- **激活环境**: `conda activate LLM`
- **安装依赖**: `pip install -r backend/requirements.txt`

`start.bat` 和 `start.sh` 脚本会自动尝试定位并使用该环境。

## 开发命令

```bash
# 后端
cd backend && pip install -r requirements.txt
python seed.py                                      # 初始化数据库 + 种子数据
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 运行后端测试
cd backend && pytest

# 前端
cd frontend && npm install
npm run dev                                         # Vite 开发服务器，端口 5173
npm run build                                       # vue-tsc 类型检查 + vite build
npm test                                            # 运行前端测试 (Vitest)

# Docker
docker-compose up -d --build

# 本地启动脚本
start.bat   (Windows)
start.sh    (Linux/WSL)
```

## 配置与环境

- **环境变量**: 项目根目录有 `.env.example` 文件，请复制为 `.env` 并填入你的配置。
- **后端配置**: 后端 (`backend/`) 目录下也有一个 `.env` 文件，用于本地开发。
- **数据库迁移**: 使用 Alembic 管理数据库结构。
  - 生成迁移脚本: `cd backend && alembic revision --autogenerate -m "Your message"`
  - 更新数据库: `cd backend && alembic upgrade head`

## 架构要点

- **认证**：JWT 存 Cookie（key=`access_token`），同时支持 `Authorization: Bearer` 兜底。`get_current_user()` 通过 cookie 从请求提取 token。
- **数据库**：`DATABASE_URL` 环境变量切换 SQLite（默认）或 PostgreSQL。SQLite 需 `check_same_thread=False`。
- **存储**：`STORAGE_BACKEND=local|smb` 控制。目录模板 `customers/{year}/{salesman}/{name}_{pinyin}/{n}-{category}/`。文件操作记入 `backend/file_audit.log`。
- **审计**：`backend/utils/audit_logger.py` 提供 `audit_log` 装饰器和 `manual_audit_log` 函数，记录到数据库 `OperationLog` 表。
- **状态机**：`enums.py` 的 `VALID_TRANSITIONS` 定义了申报批次的状态流转规则。
- **前端 API 代理**：`vite.config.ts` 配置 `/api` -> `localhost:8000`，开发时无需 CORS 配置。
- **Python 要求**：3.10+（代码使用 `list[str]` 类型注解）。

## 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 业务员 | salesman1 | sales123 |
| 审核员 | reviewer1 | review123 |

## 维护项目文档

- 每次功能修改后同步更新 `docs/` 下的对应文档
- 代码中的关键枚举（`enums.py`）、状态转换（`VALID_TRANSITIONS`）、配置常量保持与 docs 一致
- 新增 API 路由时更新 `docs/api.md`

## Changelog

- 每次修改在 `CHANGELOG.md` 追加变更记录（本地维护，不提交 git）

## 注意

- 后端测试在 `backend/tests/`（pytest，约 240 个用例）；前端测试用 Vitest
  （`npm run test:run`，注意裸 `npm test` 是 watch 模式，CI 会挂住）
- 所有 router 在 `main.py` 手动注册，新增 router 需添加 `app.include_router()`
- `ALLOWED_ORIGINS` 支持逗号分隔多个 origin
- 文件上传限制 50MB，白名单扩展名：`.pdf .doc .docx .jpg .jpeg .png`
- 新增环境变量时**必须同步 `docker-compose.yml` 的 `environment` 段**：
  compose 不使用 `env_file`，不显式转发就不会传进容器（`tests/test_deploy_config.py`
  会因此失败）。同理新增依赖 `pg_dump` 之类的系统工具时同步 `Dockerfile`
- Element Plus 图标按需引入：组件里用到图标必须显式
  `import { Xxx } from '@element-plus/icons-vue'`，`main.ts` 不再全局注册
