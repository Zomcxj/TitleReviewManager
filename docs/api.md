# API 文档

启动后端后访问 Swagger UI: http://localhost:8000/docs

## 核心 API

### 认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 用户登录 |

### 客户管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/customers/` | GET | 客户列表 |
| `/api/customers/` | POST | 创建客户 |
| `/api/customers/{id}` | GET | 客户详情 |
| `/api/customers/{id}` | PUT | 更新客户 |

### 申请管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/applications/` | GET/POST | 申请列表/创建 |
| `/api/applications/{id}` | GET/PUT | 申请详情/更新 |

### 审计与导出

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/audit/logs/` | GET | 审计日志（管理员） |
| `/api/exports/customers` | POST | 导出 Excel |

### 通知与跟进

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/notifications/` | GET | 通知列表 |
| `/api/follow-ups/` | GET/POST | 跟进记录 |

### 公海池

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/public-pool/` | GET | 公海池列表 |
| `/api/public-pool/claim/{id}` | POST | 领取客户 |
| `/api/public-pool/release/{id}` | POST | 释放客户 |

### 批量操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/batch/assign-customers` | POST | 批量分配 |
| `/api/batch/review` | POST | 批量审核 |

### 数据看板

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/stats` | GET | 看板统计 |
| `/api/dashboard/trend` | GET | 趋势分析 |
