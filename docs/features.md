# 功能说明

## Phase 1 - 基础功能

- 用户认证（JWT）
- 客户管理（CRUD）
- 申请表单
- 材料上传
- 审核工作台
- 审计日志
- Excel 导出

## Phase 2 - 通知与跟进

- 通知中心
- 跟进记录
- 跟进时间轴组件
- 自动通知（状态变更触发）

## Phase 3 - 公海池与 SLA

- 公海池管理
- SLA 超时监控（7 天无跟进自动回收）
- 自动回收任务（后台调度）
- 公海池统计看板

## Phase 4 - 批量与数据看板

- 批量分配客户
- 批量审核
- 数据看板
- 趋势分析

## 项目结构

```
TitleReviewManager/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── models.py            # 数据库模型
│   ├── schemas.py           # Pydantic 模型
│   ├── database.py          # 数据库连接
│   ├── auth.py              # 认证模块
│   ├── routers/             # API 路由
│   └── tasks/               # 后台任务
├── frontend/
│   ├── src/
│   │   ├── views/           # 页面组件
│   │   ├── components/      # 通用组件
│   │   ├── api/             # API 封装
│   │   ├── router/          # 路由配置
│   │   └── stores/          # Pinia 状态
│   └── package.json
└── tests/                   # Playwright 测试
```
