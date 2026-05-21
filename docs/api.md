# API 文档

启动后端后访问 Swagger UI: http://localhost:8000/docs

## 认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 用户登录 |
| `/api/auth/logout` | POST | 退出登录 |
| `/api/auth/me` | GET | 获取当前用户 |

## 客户管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/customers/` | GET | 客户列表（分页/关键词/状态筛选） |
| `/api/customers/` | POST | 创建客户（含拼音首字母 + NAS 目录） |
| `/api/customers/{id}` | GET | 客户详情 + 所有申报批次 |
| `/api/customers/{id}` | PUT | 更新客户 |
| `/api/customers/stats` | GET | 客户统计（仪表盘） |

## 申请管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/applications/` | GET/POST | 申请列表/创建 |
| `/api/applications/{id}` | GET/PUT | 申请详情/状态更新 |
| `/api/applications/{id}/submit-to-institution` | POST | 提交评审机构 |
| `/api/applications/{id}/reapply` | POST | 发起二次申报 |
| `/api/applications/{id}/materials/` | GET | 材料列表（含关键词/类型/状态筛选 + NAS 树） |
| `/api/applications/{id}/materials/` | POST | 上传材料 |
| `/api/applications/{id}/materials/{mid}` | DELETE | 删除材料 |
| `/api/applications/{id}/materials/{mid}` | PUT | 更新材料（备注/审核状态） |
| `/api/applications/{id}/materials/file/{mid}` | GET | 下载文件 |
| `/api/applications/{id}/materials/browse` | GET | NAS 文件目录树 |

## 审核

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/reviews/application/{app_id}` | GET | 申报审核记录 |
| `/api/reviews/material/{mat_id}` | GET | 材料审核记录 |
| `/api/reviews/` | POST | 单份审核 |
| `/api/reviews/batch-review` | POST | 批量审核 |

## 机构反馈

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/feedback/application/{app_id}` | GET | 反馈记录 |
| `/api/feedback/` | POST | 录入反馈 |
| `/api/feedback/application/{app_id}/logs` | GET | 操作日志 |

## 用户管理（管理员）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/users/` | GET | 用户列表 |
| `/api/users/{id}` | GET | 用户详情 |
| `/api/users/` | POST | 创建用户 |
| `/api/users/{id}` | PUT | 更新用户 |
| `/api/users/{id}` | DELETE | 删除用户 |
| `/api/users/change-password` | POST | 修改当前用户密码 |

## 批量操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/imports/customers` | POST | Excel 批量导入客户 |
| `/api/exports/customers` | POST | 导出客户列表 |
| `/api/exports/applications` | POST | 导出申报批次 |
| `/api/batch/assign-customers` | POST | 批量分配客户 |
| `/api/batch/review` | POST | 批量审核 |

## 通知与跟进

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/notifications/` | GET | 通知列表 |
| `/api/notifications/unread-count` | GET | 未读数量 |
| `/api/notifications/{id}/read` | PUT | 标记已读 |
| `/api/notifications/read-all` | PUT | 全部已读 |
| `/api/follow-ups/?customer_id={id}` | GET | 跟进记录 |
| `/api/follow-ups/` | POST | 添加跟进 |

## 公海池

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/public-pool/` | GET | 公海池列表 |
| `/api/public-pool/claim/{id}` | POST | 领取客户 |
| `/api/public-pool/release/{id}` | POST | 释放客户 |
| `/api/public-pool/stats` | GET | 统计 |

## 审计

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/audit/logs/` | GET | 审计日志（管理员） |

## 数据看板

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/stats` | GET | 看板统计 |
| `/api/dashboard/trend` | GET | 趋势分析 |

## 其他

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/registration/links` | POST/GET | 注册链接管理 |
| `/api/auth/lock-status` | GET | 账号锁定状态 |
