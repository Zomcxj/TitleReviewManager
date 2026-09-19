# TitleReviewManager — 职称申报材料审核与管理平台

面向职称申报服务机构的内部管理平台：从客户建档、材料收集、内部审核、机构评审到收费与证书交付的**全流程数字化**，内置数据隔离、审计防篡改、SLA 自动催办等生产级能力。

> 技术栈：Vue 3 + TypeScript + Element Plus / FastAPI + SQLAlchemy + Pydantic v2 / SQLite（开发）· PostgreSQL（生产）/ Docker

## 功能总览

| 领域 | 能力 |
|------|------|
| 客户与线索 | 建档（身份证校验位验证）、查重、公海池（认领限额 + 无跟进自动回收）、注册链接自助建档、Excel 批量导入、客户转让（自动迁移 NAS 目录） |
| 申报与材料 | 批次状态机（严格流转约束 + 管理员纠错回退）、材料分类上传与版本管理、必传清单强校验（杜绝空批次报送）、批量材料打包下载 |
| 内部审核 | 待审队列（按审核 SLA 排序、超时标红）、逐项/批量审核、机构反馈驱动状态机、docx/PDF/图片在线预览（材料不出本域） |
| 提醒与待办 | 今日待办工作台（跟进/审核/截止/回款按角色汇总）、跟进逾期、审核 SLA 超时、申报截止自动催办（同一事项每日最多一次） |
| 财务与证书 | 合同与回款登记（自动汇总收费状态）、待收款提醒、财务总览、证书状态跟踪 |
| 运营分析 | 转化漏斗（标出流失环节）、材料退回原因统计、业绩排名、申报趋势 |
| 安全 | JWT + token 撤销、会话级设备管理（单设备下线）、字段级 PII 脱敏、上传魔数校验、路径穿越防护、登录限流与锁定、安全响应头、审计日志哈希链防篡改 |
| 运维 | 软删除回收站、每日自动备份（一致性快照 + 材料归档）、系统参数在线调整、部署健康自检、前端错误上报、内置调度器（多 worker 安全） |

完整功能说明见 [docs/features.md](docs/features.md)。

## 快速开始

### 开发环境

```bash
# 后端
cd backend
pip install -r requirements.txt
cp .env.example .env            # 至少配置 JWT_SECRET_KEY
python seed.py                  # 建表 + 种子数据
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端（另一个终端）
cd frontend
npm install
npm run dev                     # http://localhost:5173，/api 自动代理到 8000
```

### 运行测试

```bash
cd backend && python -m pytest   # 121 个用例：状态机、数据隔离、上传校验、SLA、待办工作台等
cd frontend && npm test          # 前端 Vitest
```

### Docker 部署

```bash
cp .env.example .env             # 数据库密码等必填项未设置会拒绝启动
docker-compose up -d --build
curl http://localhost:8000/api/health/detail   # 部署自检
```

部署清单（HTTPS/反代/备份恢复/定时任务）见 [docs/deployment.md](docs/deployment.md)。

## 默认账号

| 角色 | 用户名 | 初始密码 |
|------|--------|----------|
| 管理员 | admin | admin123 |
| 业务员 | salesman1 | sales123 |
| 审核员 | reviewer1 | review123 |

> ⚠️ 种子账号带有 `must_change_password` 标记，首次登录**强制修改密码**后才能使用系统（拒绝常见弱口令）。生产部署请确认所有账号已完成改密。

## 项目结构

```
├── backend/
│   ├── routers/          # 21 个 API 路由模块（auth/customers/applications/materials/reviews/finance/...）
│   ├── models.py         # SQLAlchemy 模型（软删除、审计哈希链、会话表）
│   ├── schemas.py        # Pydantic 请求/响应模型
│   ├── enums.py          # 集中枚举、状态机转换表、必传材料清单、系统配置默认值
│   ├── auth.py           # JWT + token_version 撤销 + bcrypt
│   ├── storage.py        # 存储抽象层（本地 / SMB NAS）
│   ├── alembic/          # 数据库迁移
│   ├── tests/            # 121 个 pytest 用例
│   ├── tasks/            # SLA 调度、自动备份
│   └── utils/            # 数据隔离/脱敏/上传校验/调度器/催办/哈希链等 19 个工具模块
├── frontend/
│   └── src/
│       ├── views/        # 23 个页面（含今日待办工作台、功能教程、回收站、备份等）
│       ├── components/   # AdminLayout（分组侧边栏）、NotificationBell 等
│       └── stores/ api/ router/
├── docs/                 # features.md（功能说明）/ api.md（接口）/ deployment.md（部署）
├── Dockerfile            # 多阶段构建，前端产物由 FastAPI 托管
└── docker-compose.yml    # 健康检查 + 密码强制外置
```

## 存储目录结构

```
customers/{year}/{salesman}/{customer_name}_{pinyin}/{n}-{category}/{filename}
```

- 存储后端通过 `STORAGE_BACKEND=local|smb` 切换，NAS 目录随客户改名/转让自动迁移
- 全部文件操作写入 `file_audit.log`，材料下载记入数据库审计（含操作人与脱敏标记）

## 安全要点

- 认证：JWT（HTTP-only Cookie + Bearer 兜底），改密/重置/删除用户即刻撤销全部旧 token；每个登录会话独立可下线
- 数据隔离：业务员仅限名下客户（服务端统一校验，非前端过滤）；敏感字段按角色脱敏
- 上传：扩展名白名单 + 大小限制 + 文件魔数校验 + 文件名净化 + 路径越界防护
- 审计：登录/审核/回款/导出/下载全留痕，日志带 SHA-256 哈希链，改动可检出
- 限流：登录 IP/账号双维度（数据库计数，多 worker 安全）；批量操作上限与频控

## 文档

- [docs/features.md](docs/features.md) — 全部功能与设计说明
- [docs/api.md](docs/api.md) — API 一览（启动后另有 Swagger：`/docs`）
- [docs/deployment.md](docs/deployment.md) — 部署、HTTPS/反代、备份恢复、检查清单
- 系统内置「使用教程」页（登录后侧边栏入口），按角色给出每个功能的操作步骤

## 配置

环境变量通过 `.env` 管理（模板见 [.env.example](.env.example)）：数据库、JWT 密钥、存储后端、NAS、CORS、HTTPS/反代（`FORCE_HTTPS`/`TRUST_PROXY`/`COOKIE_SECURE`）、外部通知（SMTP/Webhook）、备份与调度器等，均带注释说明。
