# API 文档

启动后端后访问 Swagger UI: http://localhost:8000/docs

> 本文件按业务域列出全部端点。`{id}` 等花括号为路径参数。
> 权限列中未特别标注的端点均需登录（`get_current_user`）。

## 认证

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 用户登录（IP + 账号双维度限流，失败次数过多触发锁定） |
| `/api/auth/logout` | POST | 退出登录（吊销当前会话） |
| `/api/auth/me` | GET | 获取当前用户 |
| `/api/auth/lock-status` | GET | 账号锁定状态（登录页提示剩余锁定时间） |
| `/api/auth/sessions` | GET | 当前账号的活跃登录设备列表 |
| `/api/auth/sessions/{session_id}` | DELETE | 下线指定设备（仅能操作自己的会话） |
| `/api/auth/sessions/revoke-others` | POST | 下线除当前设备外的所有设备（怀疑账号被盗时使用） |

## 客户管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/customers/` | GET | 客户列表（分页/关键词/状态筛选） |
| `/api/customers/` | POST | 创建客户（含拼音首字母 + NAS 目录） |
| `/api/customers/{id}` | GET | 客户详情 + 所有申报批次（salesman 仅限名下客户） |
| `/api/customers/{id}` | PUT | 更新客户（salesman/admin；salesman 仅限名下客户；改名自动迁移 NAS 目录） |
| `/api/customers/{id}` | DELETE | 软删除客户（存在评审中批次时 400，可在回收站恢复） |
| `/api/customers/{id}/transfer` | PUT | 转让客户（自动迁移 NAS 目录 + 双方通知） |
| `/api/customers/batch-transfer` | POST | 批量转让（管理员） |
| `/api/customers/stats` | GET | 客户统计（仪表盘） |
| `/api/customers/salesmen` | GET | 业务员列表（转让下拉框、列表业务员列展示） |

> 审核员与业务员看到的证件号按数据范围脱敏（`utils/masking.py`），管理员可见完整值。

## 申请管理

> 申报批次没有独立的「列表/新建」端点：批次在创建客户时自动生成
> （`POST /api/customers/`，批次号形如 `BATCH-XXXXXXXX`），列表随客户详情返回
> （`GET /api/customers/{id}` 的 `applications` 字段）。二次申报走
> `POST /api/applications/{id}/reapply`。

| 端点 | 方法 | 说明 |
|------|------|------|
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
| `/api/applications/{id}/materials/download-zip` | GET | 整批材料打包下载（`?category=` 可按类别过滤；限制单次总大小，超出提示分批） |

## 审核

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/reviews/pending` | GET | 内部待审核队列（按待审材料与审核 SLA 排序；`?status=完成资料` 筛选）|
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
| `/api/batch/assign-customers` | POST | 批量分配客户（管理员；自动设置 24h SLA） |
| `/api/batch/review-batch` | POST | 批量审核 |
| `/api/batch/release-customers` | POST | 批量释放到公海（管理员） |
| `/api/batch/submit-to-institution` | POST | 批量提交评审机构（逐条校验状态/归属/材料完备性，通过者统一流转并通知） |
| `/api/batch/remind` | POST | 批量催办（向批次所属客户的业务员发送通知，admin/salesman） |

> 批量接口逐条返回 `success` 与 `skipped`（含跳过原因），不做整体事务回滚 —— 一条失败不影响其余。
> 均受条数上限与频率限制约束（`utils/batch_guard.py`）。

## 批量导入导出

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/imports/customers` | POST | Excel 批量导入客户（`.xlsx` / `.xls`） |
| `/api/exports/template` | GET | 下载 Excel 批量导入模板（salesman/admin） |
| `/api/exports/customers` | POST | 导出客户列表（salesman/admin，流式导出，上限 5 万行） |
| `/api/exports/applications` | POST | 导出申报批次（salesman/admin，流式导出，上限 5 万行） |

> 导出支持 `?mask=true` 脱敏身份证号与手机号 —— **对外发送的表格建议开启**。

## Word 表单导入

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/word-import/template` | GET | 下载 Word 填报模板（salesman/admin） |
| `/api/word-import/parse` | POST | 解析填报好的 `.docx` 并自动创建客户（salesman/admin） |

> 解析读取文档第一个表格的「键/值」两列，必填 `姓名` 与 `身份证号`。
> 身份证号已存在时返回 400 并提示归属客户，避免重复建档。
> 解析全部在本地完成（python-docx），**不上传任何第三方服务** —— 模板含身份证号字段。

## 专属注册链接

业务员生成专属链接发给客户，客户自助填写信息建档，无需系统账号。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/registration-links/` | GET | 链接列表（admin 看全部，salesman 仅自己创建的） |
| `/api/registration-links/` | POST | 创建注册链接（可设有效天数与最大使用次数） |
| `/api/registration-links/{token_id}` | DELETE | 停用链接（`is_active=false`，保留记录） |
| `/api/registration-links/{token_id}/hard` | DELETE | 彻底删除链接（仅管理员） |
| `/api/registration-links/validate/{token_value}` | GET | 校验链接有效性（公开，返回业务员姓名与剩余次数） |
| `/api/registration-links/self-register` | POST | 客户自助注册（公开，凭有效 token 建档） |

> 生成的链接形如 `/apply?token=<token>`，完整外链基于 `PUBLIC_URL` 环境变量拼接
> （未设置时自动探测本机局域网 IP）。token 使用 `secrets.token_urlsafe(32)`。

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
| `/api/follow-ups/schedule` | GET | 待跟进日程（`?scope=today\|overdue\|week`；salesman 仅名下客户） |
| `/api/follow-ups/summary` | GET | 待跟进汇总（工作台卡片与侧边提醒） |

> 通知可配置外部渠道推送（邮件/Webhook），见 `.env.example` 的「外部通知渠道」一节。
> 外部推送失败不影响站内通知落库，仅记 warning。

## 公海池

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/public-pool/` | GET | 公海池列表（`/` 与空路径等价） |
| `/api/public-pool/claim/{id}` | POST | 领取客户（受持有上限约束） |
| `/api/public-pool/release/{id}` | POST | 释放客户 |
| `/api/public-pool/stats` | GET | 统计 |

> 公海客户尚未归属，除管理员外证件号一律脱敏 —— 避免被批量抓取证件号。
> 客户超过 `POOL_RECOVERY_DAYS` 天无跟进会被调度器自动回收进公海。

## 数据看板

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard/stats` | GET | 看板统计（按角色过滤） |
| `/api/dashboard/trend` | GET | 趋势分析 |
| `/api/dashboard/performance` | GET | 业绩排行（登录用户） |
| `/api/dashboard/rejection-stats` | GET | 退回原因统计 |
| `/api/dashboard/workbench` | GET | 今日待办：跟进、内部审核、申报截止、待收款（按角色过滤） |
| `/api/dashboard/funnel` | GET | 转化漏斗：咨询 → 建档 → 提交机构 → 通过（`?days=` 默认 180） |

## 审计

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/audit/` | GET | 审计日志（管理员） |
| `/api/audit/logs` | GET | 同上（等价别名） |
| `/api/audit/logs/resource/{resource_type}/{resource_id}` | GET | 某条业务记录的操作历史 |
| `/api/audit/export` | GET | 导出审计日志 xlsx（管理员，流式导出，上限 1 万行） |
| `/api/audit/verify-chain` | GET | 校验审计日志哈希链完整性（管理员；`?limit=` 只校验最近 N 条） |
| `/api/audit/backfill-chain` | POST | 为历史日志补算哈希链（管理员，功能上线后一次性调用） |

> 审计日志带哈希链：任何一条被修改或删除都会导致后续链断裂，`verify-chain` 返回
> `broken_at` 定位被改动的记录。校验失败本身也会落一条审计（该条在链上，攻击者改不掉历史）。

## 数据备份（管理员）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/backup/` | GET | 备份列表（按时间倒序）+ 备份目录与启用状态 |
| `/api/backup/run` | POST | 立即执行一次备份（同步返回结果摘要） |
| `/api/backup/config` | GET | 当前备份配置（供管理界面展示） |

> `run` 包含材料文件打包，数据量大时可能耗时数分钟。生产环境建议依赖调度器凌晨自动执行，
> 此接口主要用于小数据量手动验证或紧急备份 —— 前端调用需设置足够的请求超时。
>
> 备份失败会向所有管理员发送站内通知（此前只写日志，等于失败被静默吞掉）。
> 每次成功备份后调度器会自动做一次**恢复演练**（在临时位置还原并校验数据可读），
> 可用 `BACKUP_DRILL_ENABLED=0` 关闭。

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

## 收费/合同/回款与证书

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/finance/application/{id}` | GET | 查询批次财务与证书信息（含回款明细） |
| `/api/finance/application/{id}` | PUT | 更新合同/收费/证书信息（salesman 限名下） |
| `/api/finance/application/{id}/payments` | POST | 登记回款（自动汇总已收金额与收费状态） |
| `/api/finance/payments/{id}` | DELETE | 删除回款记录（管理员） |
| `/api/finance/summary` | GET | 财务总览（管理员） |
| `/api/finance/pending` | GET | 待收款提醒（按欠款额倒序） |

## 前端错误上报

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/client-errors/report` | POST | 上报前端错误（**匿名可用**，按 IP 限流 30 次/5 分钟） |
| `/api/client-errors/` | GET | 错误列表（管理员，分页） |
| `/api/client-errors/{error_id}` | DELETE | 删除单条记录（管理员） |
| `/api/client-errors/` | DELETE | 清空全部记录（管理员） |

> 设计为匿名可上报：登录页出错时用户还没有 token，强制鉴权会丢掉最关键的一类错误。
> message/stack 均截断保存（2000 / 5000 字符），避免超大 payload 撑爆数据库。

## 客户进度自助查询（公开，无需登录）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/public-progress/query` | POST | 凭身份证号 + 手机号后 4 位查进度（IP 限流 20 次/5 分钟） |
| `/api/public-progress/status` | GET | 服务可用性探针 |

> 返回内容仅含批次号、专业、级别、状态、进度时间线、材料统计、最近机构反馈，**不含**身份证号/手机号/工作单位等敏感字段。

## 其他

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/health/detail` | GET | 配置自检（数据库/密钥强度/存储可写/通知渠道/调度器） |
