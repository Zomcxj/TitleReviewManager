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
| `/api/customers/{id}` | GET | 客户详情 + 所有申报批次（salesman 仅限名下客户） |
| `/api/customers/{id}` | PUT | 更新客户（salesman/admin；salesman 仅限名下客户；改名自动迁移 NAS 目录） |
| `/api/customers/{id}/transfer` | PUT | 转让客户（自动迁移 NAS 目录 + 双方通知） |
| `/api/customers/batch-transfer` | POST | 批量转让（管理员） |
| `/api/customers/stats` | GET | 客户统计（仪表盘） |

## 申请管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/applications/` | GET/POST | 申请列表/创建 |
| `/api/applications/{id}` | GET/PUT | 申请详情/状态更新 |
| `/api/applications/{id}/submit-to-institution` | POST | 提交评审机构（**校验必传材料齐全**，缺料 400） |
| `/api/applications/{id}/material-checklist` | GET | 材料完备性清单（必传/已传/缺失） |
| `/api/applications/{id}/cycle` | PUT | 设置申报年度与截止时间 |
| `/api/applications/{id}/revert-status` | POST | 状态回退纠错（仅管理员，需填原因） |
| `/api/applications/{id}/reapply` | POST | 发起二次申报（**检测重复申报**：同客户+同专业+同级别已有进行中批次时 400） |
| `/api/applications/{id}/materials/` | GET | 材料列表（含关键词/类型/状态筛选 + NAS 树） |
| `/api/applications/{id}/materials/` | POST | 上传材料 |
| `/api/applications/{id}/materials/{mid}` | DELETE | 删除材料 |
| `/api/applications/{id}/materials/{mid}` | PUT | 更新材料（备注：salesman/admin；审核状态：reviewer/admin） |
| `/api/applications/{id}/materials/file/{mid}` | GET | 下载文件（salesman 仅限名下客户） |
| `/api/applications/{id}/materials/browse` | GET | NAS 文件目录树（salesman 仅限名下客户） |

## 审核

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/reviews/application/{app_id}` | GET | 申报审核记录 |
| `/api/reviews/material/{mat_id}` | GET | 材料审核记录 |
| `/api/reviews/` | POST | 单份审核（reviewer/admin） |
| `/api/reviews/batch-review` | POST | 批量审核（reviewer/admin；受状态机约束） |
| `/api/reviews/{review_id}/attachment` | GET | 下载审核附件（登录用户） |

## 机构反馈

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/feedback/application/{app_id}` | GET | 反馈记录 |
| `/api/feedback/` | POST | 录入反馈（reviewer/admin；仅"提交评审机构审核"状态可录入并驱动状态机） |
| `/api/feedback/{feedback_id}/attachment` | GET | 下载反馈附件（登录用户） |
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
| `/api/users/{id}/reset-password` | POST | 管理员重置用户密码（需验证管理员密码） |

> 注：系统不再存储/返回明文密码，原 `verify-admin-password`（查看明文密码）端点已移除。删除用户前需先转让其名下客户。

## 批量操作

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/imports/customers` | POST | Excel 批量导入客户 |
| `/api/exports/customers` | POST | 导出客户列表（salesman/admin） |
| `/api/exports/applications` | POST | 导出申报批次（salesman/admin） |
| `/api/batch/assign-customers` | POST | 批量分配客户（管理员；自动设置 24h SLA） |
| `/api/batch/review` | POST | 批量审核 |
| `/api/batch/release-customers` | POST | 批量释放到公海（管理员） |

## 通知与跟进

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/notifications/` | GET | 通知列表 |
| `/api/notifications/unread-count` | GET | 未读数量 |
| `/api/notifications/read/{id}` | POST | 标记已读 |
| `/api/notifications/read-all` | POST | 全部已读 |
| `/api/notifications/{id}` | DELETE | 删除单条通知 |
| `/api/notifications/clear-read` | DELETE | 清理本人已读通知 |
| `/api/follow-ups/customer/{id}` | GET | 跟进记录 |
| `/api/follow-ups/` | POST | 添加跟进（salesman/admin；更新客户最后跟进时间） |
| `/api/follow-ups/{id}` | DELETE | 删除跟进（创建者或管理员） |

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
| `/api/dashboard/stats` | GET | 看板统计（按角色过滤） |
| `/api/dashboard/trend` | GET | 趋势分析 |
| `/api/dashboard/performance` | GET | 业绩排行（登录用户） |

## 其他

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/registration/links` | POST/GET | 注册链接管理 |
| `/api/auth/lock-status` | GET | 账号锁定状态 |

## 客户进度自助查询（公开，无需登录）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/public-progress/query` | POST | 凭身份证号 + 手机号后 4 位查进度（IP 限流 20 次/5 分钟） |
| `/api/public-progress/status` | GET | 服务可用性探针 |

> 返回内容仅含批次号、专业、级别、状态、进度时间线、材料统计、最近机构反馈，**不含**身份证号/手机号/工作单位等敏感字段。

## 收费/合同/回款与证书

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/finance/application/{id}` | GET | 查询批次财务与证书信息（含回款明细） |
| `/api/finance/application/{id}` | PUT | 更新合同/收费/证书信息（salesman 限名下） |
| `/api/finance/application/{id}/payments` | POST | 登记回款（自动汇总已收金额与收费状态） |
| `/api/finance/payments/{id}` | DELETE | 删除回款记录（管理员） |
| `/api/finance/summary` | GET | 财务总览（管理员） |
| `/api/finance/pending` | GET | 待收款提醒（按欠款额倒序） |

## 系统配置（管理员）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/system-config/` | GET | 读取全部配置项（含标签与默认值） |
| `/api/system-config/` | PUT | 批量更新配置（保存后立即生效） |
| `/api/system-config/reset` | POST | 恢复默认值 |

## 回收站（管理员）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/recycle-bin/` | GET | 已软删除记录（可按 `resource_type` 过滤） |
| `/api/recycle-bin/restore` | POST | 恢复记录 |
| `/api/recycle-bin/purge/{type}/{id}` | DELETE | 彻底删除（带依赖校验） |

## 客户删除

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/customers/{id}` | DELETE | 软删除客户（存在评审中批次时 400，可在回收站恢复） |
