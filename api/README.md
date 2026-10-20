# API 总览

本目录是 DataVisualServer 后端所有功能接口的归档与模块化拆分。
所有蓝图在 `app.py` 中注册，共享依赖（线程池 / 任务表 / 目录 / 鉴权）由
`api/common.py:init_app()` 注入，用 `current_app.config[...]` 读取。

## 目录结构

```
api/
├── __init__.py        # 蓝图总导出
├── common.py          # 共享依赖注入、API Key 校验、任务表回收（prune_tasks）
├── chart_api.py       # 图表生成 / 图表 HTML
├── task_api.py        # 任务查询 / 取消
├── code_api.py        # 可视化代码补全
├── data_api.py        # 数据预览 / 多模态抽表
├── conversation_api.py# 历史对话 CRUD
├── cleanup_api.py     # runtime 目录清理
└── health_api.py      # 部署探针（health / ready）
```

## 所有接口一览

| 方法 | 路径 | 所属模块 | 鉴权 | 简介 |
|------|------|----------|:----:|------|
| `POST` | `/api/generate-chart-with-prompt` | `chart_api.py` | ✅ | 提交图表生成任务（异步） |
| `GET`  | `/api/task/<task_id>` | `task_api.py` | ✅ | 查询任务进度 / 结果 |
| `POST` | `/api/task/<task_id>/cancel` | `task_api.py` | ✅ | 请求取消任务 |
| `GET`  | `/api/chart/<chart_id>` | `chart_api.py` | ❌ | 获取生成的图表 HTML |
| `POST` | `/api/complete-viz-code` | `code_api.py` | ✅ | 现有 Python 文件追加可视化代码 |
| `POST` | `/api/data-profile` | `data_api.py` | ✅ | 数据预览 / 图片·PDF 抽表 |
| `GET`  | `/api/charts-dir` | `data_api.py` | ✅ | 取图表输出目录 |
| `GET`  | `/api/conversations` | `conversation_api.py` | ✅ | 历史对话列表（分页） |
| `GET`  | `/api/conversations/<id>` | `conversation_api.py` | ✅ | 对话详情（含 agent_logs） |
| `DELETE` | `/api/conversations/<id>` | `conversation_api.py` | ✅ | 删除单条对话 |
| `DELETE` | `/api/conversations/oldest` | `conversation_api.py` | ✅ | 删除最早 N 条对话 |
| `DELETE` | `/api/conversations/batch` | `conversation_api.py` | ✅ | 批量删除对话 |
| `PUT`  | `/api/conversations/<id>/prompt` | `conversation_api.py` | ✅ | 修改用户提示词 |
| `POST` | `/api/cleanup` | `cleanup_api.py` | ✅ | 清理超期 runtime 文件 |
| `GET`  | `/api/health` | `health_api.py` | ❌ | 存活探针（liveness） |
| `GET`  | `/api/ready` | `health_api.py` | ❌ | 就绪探针（readiness） |
| `WS`   | `/ws/task/<task_id>` | `app.py` | ✅ | 任务进度推送 |
| `WS`   | `/ws/trace/<task_id>` | `app.py` | ✅ | trace / token / error 推送 |

> 鉴权列 ✅ 表示：`SERVICE_API_KEY` 非空时需带 `X-API-Key` 或表单 `api_key`。
> 部署探针 `/api/health`、`/api/ready` 按约定**不鉴权**。

---

### POST /api/generate-chart-with-prompt

提交可视化任务（文件数据源 / 数据库源 / API 源三选一）。支持
`multipart/form-data` 与 `application/x-www-form-urlencoded`。

#### 表单字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `files` | 条件 | File[] | 上传的数据文件。CSV / Excel / JSON / Parquet / 文档 / **图片 / PDF** 都支持 |
| `db_config` | 条件 | JSON string | 数据库连接配置 |
| `api_config` | 条件 | JSON string | 外部 API 数据源配置 |
| `user_prompt` | 可选 | string | 可视化需求描述 |
| `config` | 可选 | string | 图表配置 JSON（宽高 / 主题 / 配色） |
| `model_url` | 可选 | string | LLM 端点地址（默认走 `.env`） |
| `model_type` | 可选 | string | 模型名 |
| `model_api_key` | 可选 | string | 模型密钥（默认走 `.env`） |
| `mcp_prompt` | 可选 | string | MCP 工具提示 |
| `skill_prompt` | 可选 | string | Skill 提示 |
| `viz_mode` | 可选 | string | `agent` / `auto`（默认，自主流水线）、`legacy` / `chart` / `scientific`（固定 plan 流水线） |

> 图片 / PDF 会先经视觉模型抽成表格，再进入后续 series 拆分与图表生成。
> 视觉模型凭证优先用请求里的 `model_url` / `model_api_key`，其次
> `VISION_BASE_URL` / `VISION_API_KEY`，最后 `BASE_URL` / `API_KEY`。

#### 响应

```
202 Accepted
{
  "task_id": "abc123...",
  "status": "pending"
}
```

后续用 `GET /api/task/{task_id}` 轮询，或订阅 `/ws/task/{task_id}`。

#### 鉴权

`SERVICE_API_KEY` 非空时，请求头带：

```
X-API-Key: <your_key>
```

---

### GET /api/task/{task_id}

查询异步任务状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |
| `status` | string | pending / running / success / failed / cancelled |
| `result` | object | 成功时有值 |
| `error` | string | 失败时有值 |
| `raw` | object | 完整 successful_charts / failed_plans 列表 |
| `created_at` | string | ISO 时间戳（任务表回收依据） |

任务表只保留终态任务一段时间，避免服务长期运行内存膨胀：

| 环境变量 | 默认值 | 说明 |
|------|--------|------|
| `TASK_RETENTION_SECONDS` | `3600` | 终态任务保留秒数，超期在下一次提交时清理 |
| `TASK_MAX_ENTRIES` | `500` | 任务表条目上限，超限按时间从旧到新淘汰终态任务 |

进行中的任务永不清理。

---

### POST /api/task/{task_id}/cancel

请求取消任务。取消是协作式的：流水线在计划 / 执行 / 生成阶段检查取消标志。

```
202 Accepted
{"detail": "Cancel requested", "task_id": "..."}
```

任务已是终态时返回 `400`，任务不存在返回 `404`。

---

### GET /api/chart/{chart_id}

获取已生成图表的 HTML 文件。

| 字段 | 类型 | 说明 |
|------|------|------|
| `chart_id` | string | 文件名，如 `chart_1_20260718_130443.html` |

已做路径穿越防护；先在 `CHARTS_DIR/chart_id` 查找，不存在再 `rglob` 递归
查找（兼容旧版 `charts/xxx/charts/*.html` 结构）。

---

### POST /api/complete-viz-code

在已有 Python 代码末尾追加可视化代码片段（科学计算 / 数据分析脚本）。

#### 请求体

1. **application/json**

   ```json
   {
     "code_file_paths": ["d:/project/a.py"],
     "user_prompt": "画一个柱状图展示各列的统计值",
     "scientific_lib": "matplotlib",
     "model_url": "...",
     "model_type": "...",
     "model_api_key": "..."
   }
   ```

2. **multipart/form-data**
   - `code_files`：上传 `.py` 文件列表
   - `code_file_paths`：服务器路径列表（分号 / 换行分隔）
   - 其余字段同上

#### 响应

```json
{
  "snippet": "import matplotlib.pyplot as plt\n...",
  "explanation": "...",
  "libs": ["matplotlib", "numpy"]
}
```

---

### POST /api/data-profile

独立于图表生成的数据预览接口：上传文件后直接返回 schema、前 10 行预览、
列语义角色与推荐图表模式。

#### 表单字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `files` | 是 | 一个或多个文件（表格 / 文档 / 图片 / PDF） |
| `hint` | 否 | 用户分析意图；图片/PDF 抽表时用于选择主表 |
| `model_url` / `model_api_key` | 否 | 视觉模型凭证（仅多模态抽表需要） |

#### 响应

```json
{
  "profile": {
    "table_name": "sales",
    "row_count": 4,
    "schema": [{"name": "年份", "type": "int64"}],
    "preview": [{"年份": 2023, "销售额": 1200}],
    "series_index": "...",
    "source_kind": "file"
  },
  "file_count": 1
}
```

图片 / PDF 走视觉模型时**会调用 LLM**；纯表格文件不调用。

---

### 历史对话

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/conversations?limit=50&offset=0` | 列表 + 总数（`limit` 上限 200） |
| `GET` | `/api/conversations/<id>` | 详情（含完整 agent_logs） |
| `DELETE` | `/api/conversations/<id>` | 删除单条（联动删图表 + trace） |
| `DELETE` | `/api/conversations/oldest?count=N` | 删除最早 N 条 |
| `DELETE` | `/api/conversations/batch` | 请求体 `{"ids": [...]}` |
| `PUT` | `/api/conversations/<id>/prompt` | 请求体 `{"user_prompt": "..."}` |

存储为 SQLite（`CONVERSATION_DB_PATH`，默认 `runtime/logs/conversations.db`）。

---

### POST /api/cleanup?max_age_days=7

清理 `runtime/` 下超期的 `uploads` / `datasets` / `traces` / `charts`。
`max_age_days=0` 表示全部清理（谨慎使用）。

#### 响应

```json
{
  "detail": "清理完成（超 7 天）",
  "max_age_days": 7,
  "removed_files": 12,
  "removed_dirs": 3,
  "bytes_freed": 1048576,
  "bytes_freed_mb": 1.0,
  "details": []
}
```

---

### GET /api/health

存活探针（liveness）：进程可达即 `200`。适合容器 livenessProbe。

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_seconds": 12.7,
  "pid": 11852,
  "tasks": {
    "pending": 0, "running": 1, "success": 3, "failed": 0,
    "cancelled": 0, "total": 4, "finished": 3
  }
}
```

### GET /api/ready

就绪探针（readiness）：检查上传目录、图表目录可写，对话库可访问。
全部通过返回 `200` + `{"status": "ready"}`，否则 `503` + `{"status": "not_ready"}`。

```json
{
  "status": "ready",
  "checks": {
    "upload_dir": {"path": "...\\runtime\\uploads", "ok": true},
    "charts_dir": {"path": "...\\runtime\\charts", "ok": true},
    "conversation_db": {"ok": true}
  }
}
```

---

## WebSocket

| 路径 | 说明 |
|------|------|
| `/ws/task/<task_id>` | 任务状态推送（前端生成流程使用） |
| `/ws/trace/<task_id>` | trace / token / error 事件流 |

鉴权：连接时带 `X-API-Key`（与 HTTP 一致）。

---

## 环境变量（影响 API 行为）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LOG_PATH` | `runtime/logs/datavisual.jsonl` | 结构化日志输出（JSON Lines） |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `MAX_CONTENT_LENGTH` | `52428800`（50MB） | 单次请求 Body 上限 |
| `TEMP_UPLOAD_DIR` | `runtime/uploads/` | 上传暂存目录 |
| `TEMP_DATASETS_DIR` | `runtime/datasets/` | 数据接入会话目录 |
| `CHARTS_DIR` | `runtime/charts/` | 图表产物目录 |
| `SERVICE_API_KEY` | `""` | API 鉴权密钥（空 = 不鉴权） |
| `TASK_MAX_WORKERS` | `2` | 异步任务并发度 |
| `TASK_RETENTION_SECONDS` | `3600` | 终态任务保留秒数 |
| `TASK_MAX_ENTRIES` | `500` | 任务表条目上限 |
| `VISION_MODEL_NAME` | `glm-4.5v` | 多模态抽表模型（非智谱需显式改） |
| `VISION_BASE_URL` / `VISION_API_KEY` | `""` | 视觉模型独立凭证（可选） |
| `VISION_MAX_IMAGE_SIDE` | `2000` | 上传前图片最大边长（像素） |
| `VISION_MAX_PDF_PAGES` | `5` | PDF 视觉兜底最多解析页数 |
| `FLASK_HOST` | `0.0.0.0` | 监听地址 |
| `FLASK_PORT` | `5000` | 监听端口 |
| `FLASK_DEBUG` | `false` | 是否开启 debug |

---

## 错误响应格式

```json
{"detail": "错误描述文字"}
```

| HTTP 码 | 典型场景 |
|---------|----------|
| `400` | 参数缺失 / JSON 解析失败 / 任务已终态 |
| `401` | API Key 校验不通过 |
| `404` | task / chart / 对话不存在 |
| `500` | 内部异常（ServiceError / ConfigError / 未预期 Exception） |
| `503` | `/api/ready` 依赖未就绪 |

---

## 扩展与维护

1. 在对应模块的 `*_api.py` 里加路由；新领域则新增 `xxx_api.py` + Blueprint
2. 在 `api/__init__.py` 导出新 Blueprint
3. 在 `app.py` 中 `app.register_blueprint(...)` 注册
4. 在本表追加文档行

共享依赖（线程池、任务表、目录、鉴权）统一在 `api/common.py` 通过
`flask.current_app.config["KEY"]` 访问，不跨模块直接 import 全局变量。
