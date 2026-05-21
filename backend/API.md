# 职称服务内部管理平台 · 后端 API 文档

> 基础地址：`http://localhost:8000`
> 认证方式：JWT Token 通过 Cookie 传递（`access_token`）

---

## 1. 认证模块 `/api/auth`

### 1.1 登录

```
POST /api/auth/login
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码 |

**响应**：登录成功后设置 `access_token` Cookie，返回用户信息。

```json
{
  "message": "登录成功",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "real_name": "系统管理员"
  }
}
```

### 1.2 退出登录

```
POST /api/auth/logout
```

**作用**：清除 `access_token` Cookie。

### 1.3 获取当前用户

```
GET /api/auth/me
```

**作用**：通过 Cookie 中的 Token 获取当前登录用户信息。需要认证。

---

## 2. 客户管理模块 `/api/customers`

### 2.1 客户列表

```
GET /api/customers/?page=1&page_size=20&keyword=&status=
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 20 |
| keyword | string | 否 | 搜索关键词（姓名/身份证/手机号） |
| status | string | 否 | 按申报状态筛选 |

**作用**：获取客户列表及各自最新申报状态。业务员只能看到自己负责的客户。

### 2.2 客户详情

```
GET /api/customers/{customer_id}
```

**作用**：获取客户基本信息和所有申报批次（含材料数量）。

### 2.3 创建客户（自助申报）

```
POST /api/customers/
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 姓名 |
| id_number | string | 是 | 身份证号（唯一） |
| phone | string | 否 | 手机号 |
| education | string | 否 | 学历 |
| current_title | string | 否 | 现职称 |
| current_title_year | int | 否 | 取得现职称年份 |
| work_unit | string | 否 | 工作单位 |
| position | string | 否 | 职务 |
| professional_years | int | 否 | 专业技术工作年限 |
| project_experiences | string | 否 | 项目经历 JSON 字符串 |

**作用**：客户通过自助链接填写信息提交后自动创建客户档案和首个申报批次（状态为"初次申报"）。

### 2.4 更新客户

```
PUT /api/customers/{customer_id}
Content-Type: application/json
```

**作用**：业务员修改客户基本信息。

### 2.5 统计数据

```
GET /api/customers/stats
```

**作用**：获取各状态申报数量、总申报数、今日新增。用于仪表盘展示。

---

## 3. 申报管理模块 `/api/applications`

### 3.1 获取申报批次

```
GET /api/applications/{application_id}
```

### 3.2 更新申报批次

```
PUT /api/applications/{application_id}
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | 新状态（受状态机约束） |
| professional_category | string | 否 | 申报专业 |
| title_level | string | 否 | 申报级别 |
| assigned_reviewer_id | int | 否 | 指派审核员 |
| institution_name | string | 否 | 报送机构名称 |

**作用**：更新申报批次信息，状态变更受状态机约束并记录操作日志。

**合法状态流转**：
- `初次申报` → `资料补充` | `完成资料`
- `资料补充` → `完成资料`
- `完成资料` → `提交评审机构审核` | `返修`
- `提交评审机构审核` → `通过` | `不通过` | `返修`
- `返修` → `资料补充` | `完成资料` | `提交评审机构审核`
- `不通过` → `二次申报`
- `二次申报` → `资料补充` | `完成资料`

### 3.3 提交评审机构

```
POST /api/applications/{application_id}/submit-to-institution
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| institution_name | string | 是 | 报送机构名称 |

**作用**：业务员将"完成资料"状态的申报提交至外部评审机构。状态变为"提交评审机构审核"。

### 3.4 发起二次申报

```
POST /api/applications/{application_id}/reapply
```

**作用**：基于"不通过"的批次创建新的二次申报批次，复用原专业和级别信息。

---

## 4. 材料管理模块 `/api/applications/{application_id}/materials`

### 4.1 材料列表

```
GET /api/applications/{application_id}/materials/
```

**作用**：获取该申报批次下所有上传的材料。支持筛选参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| keyword | string | 否 | 文件名关键词 |
| category | string | 否 | 材料类型（身份证明/学历学位/...） |
| audit_status | string | 否 | 审核状态（待审核/已通过/已标记问题） |

**响应**：
```json
{
  "items": [{ "id": 1, "category": "身份证明", "filename": "id_front.pdf", ... }],
  "tree": [{ "name": "1-身份证明", "children": [{ "name": "id_front.pdf", "path": "...", "isLeaf": true }] }]
}
```

### 4.2 上传材料

```
POST /api/applications/{application_id}/materials/
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category | string | 是 | 材料类型（身份证明/学历学位/职称证书/聘用/劳动合同/业绩成果/论文著作/继续教育/其他材料） |
| file | file | 是 | 文件 |

**作用**：业务员上传申报材料。文件存储到 NAS 目录模板 `customers/{year}/{salesman}/{customer}_{pinyin}/{category_number}-{category_name}/{filename}`。保留原始文件名，同类型自动版本递增，记录操作日志 + 文件审计日志。

### 4.3 删除材料

```
DELETE /api/applications/{application_id}/materials/{material_id}
```

**作用**：删除材料记录和对应文件。

### 4.4 更新材料

```
PUT /api/applications/{application_id}/materials/{material_id}
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| remark | string | 否 | 备注 |
| audit_status | string | 否 | 审核状态（待审核/已通过/已标记问题） |

### 4.5 下载材料文件

```
GET /api/applications/{application_id}/materials/file/{material_id}
```

**作用**：下载材料原始文件。

---

## 5. 审核模块 `/api/reviews`

### 5.1 获取申报审核记录

```
GET /api/reviews/application/{application_id}
```

**作用**：获取某申报批次的所有审核记录。

### 5.2 获取材料审核记录

```
GET /api/reviews/material/{material_id}
```

### 5.3 创建审核记录

```
POST /api/reviews/
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| material_id | int | 否 | 材料 ID |
| application_id | int | 否 | 申报批次 ID |
| result | string | 是 | 审核结果（通过/退回） |
| issue_type | string | 否 | 问题类型（材料缺失/不清晰/内容错误/已过期/内容需修改） |
| description | string | 否 | 详细说明 |
| review_file | file | 否 | 修订稿文件 |

**作用**：审核员对单份材料做出审核决定，标记问题时自动更新材料审核状态。

### 5.4 批量审核

```
POST /api/reviews/batch-review
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| application_id | int | 是 | 申报批次 ID |
| overall_result | string | 是 | 总体结果（通过/退回） |
| review_details | array | 是 | 每项材料的审核详情 |
| review_details[].material_id | int | 是 | 材料 ID |
| review_details[].description | string | 否 | 审核说明 |
| review_details[].issue_type | string | 否 | 问题类型 |
| description | string | 否 | 总体说明 |

**作用**：审核员批量处理多份材料。全部通过时自动将申报状态改为"完成资料"；退回时改为"资料补充"并生成问题清单。

---

## 6. 机构反馈模块 `/api/feedback`

### 6.1 获取反馈记录

```
GET /api/feedback/application/{application_id}
```

### 6.2 创建机构反馈

```
POST /api/feedback/
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| application_id | int | 是 | 申报批次 ID |
| feedback_type | string | 是 | 反馈类型（通过/不通过/返修） |
| content | string | 否 | 反馈意见内容 |
| attachment | file | 否 | 附件（如机构反馈扫描件） |

**作用**：业务员录入外部评审机构的反馈结果，自动更新申报状态并记录操作日志。

### 6.3 操作日志

```
GET /api/feedback/application/{application_id}/logs
```

**作用**：获取某申报批次的完整操作日志（状态变更、材料操作、审核记录等）。

---

## 7. 用户管理模块 `/api/users`

管理员专属。所有端点需要 `admin` 角色。

### 7.1 用户列表

```
GET /api/users/
```

### 7.2 创建用户

```
POST /api/users/
Content-Type: application/json
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名（2-50 字符，字母数字下划线） |
| password | string | 是 | 密码（6-128 字符） |
| role | string | 是 | admin / salesman / reviewer |
| real_name | string | 否 | 真实姓名 |

### 7.3 更新用户

```
PUT /api/users/{user_id}
```

### 7.4 删除用户

```
DELETE /api/users/{user_id}
```

不能删除自己。

### 7.5 修改密码（当前用户）

```
POST /api/users/change-password
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| old_password | string | 是 | 原密码 |
| new_password | string | 是 | 新密码（6-128 字符） |

---

## 8. 批量导入模块 `/api/imports`

### 8.1 批量导入客户

```
POST /api/imports/customers
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | .xlsx / .xls 文件 |

Excel 格式要求：
- 第一行为列名
- 必需列：`客户姓名`、`身份证号`
- 可选列：`手机号`、`学历`、`现职称`、`工作单位`、`岗位`

---

## 9. 角色权限矩阵

| 操作 | 业务员 | 审核员 | 管理员 |
|------|--------|--------|--------|
| 查看客户列表 | 仅自己负责 | 全部 | 全部 |
| 查看客户详情 | 是 | 是 | 是 |
| 创建客户（自助） | - | - | - |
| 上传/删除材料 | 是 | - | 是 |
| 提交内部审核 | 是 | - | 是 |
| 提交评审机构 | 是 | - | 是 |
| 录入机构反馈 | 是 | - | 是 |
| 发起二次申报 | 是 | - | 是 |
| 审核材料 | - | 是 | 是 |
| 批量通过/退回 | - | 是 | 是 |
| 查看审核记录 | 是 | 是 | 是 |
| 查看操作日志 | 是 | 是 | 是 |
| 查看统计仪表盘 | 是 | 是 | 是 |

---

## 10. 数据结构

### 客户表 (customers)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| name | string | 姓名 |
| id_number | string | 身份证号（唯一） |
| phone | string | 手机号 |
| education | string | 学历 |
| current_title | string | 现职称 |
| current_title_year | int | 取得年份 |
| work_unit | string | 工作单位 |
| position | string | 职务 |
| professional_years | int | 工作年限 |
| project_experiences | text | 项目经历 JSON |
| assigned_salesman_id | int | 所属业务员 |
| created_at | datetime | 创建时间 |

### 申报批次表 (applications)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| customer_id | int | 所属客户 |
| professional_category | string | 申报专业 |
| title_level | string | 申报级别 |
| status | string | 当前状态 |
| batch_number | string | 批次号（唯一） |
| submitted_at | datetime | 提交机构时间 |
| institution_name | string | 报送机构 |
| assigned_reviewer_id | int | 指派审核员 |
| created_at | datetime | 创建时间 |

### 材料表 (materials)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| application_id | int | 所属批次 |
| category | string | 材料类型 |
| filename | string | 原始文件名 |
| file_path | string | 存储路径 |
| file_size | int | 文件大小 |
| uploader_id | int | 上传者 |
| audit_status | string | 审核状态 |
| remark | text | 备注 |
| created_at | datetime | 上传时间 |

### 审核记录表 (reviews)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| material_id | int | 关联材料 |
| application_id | int | 关联批次 |
| reviewer_id | int | 审核员 |
| result | string | 审核结果 |
| issue_type | string | 问题类型 |
| description | text | 详细说明 |
| review_file_path | string | 修订稿路径 |
| created_at | datetime | 审核时间 |

### 机构反馈表 (feedbacks)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| application_id | int | 关联批次 |
| feedback_type | string | 反馈类型 |
| content | text | 反馈意见 |
| attachment_path | string | 附件路径 |
| created_by_id | int | 录入人 |
| created_at | datetime | 创建时间 |

### 操作日志表 (operation_logs)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| application_id | int | 关联批次 |
| customer_id | int | 关联客户 |
| action | string | 操作名称 |
| detail | text | 操作详情 |
| actor_id | int | 操作人 |
| created_at | datetime | 操作时间 |

---

## 11. 默认测试账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 业务员 | salesman1 | sales123 |
| 审核员 | reviewer1 | review123 |
