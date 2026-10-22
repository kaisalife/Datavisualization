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
| `POST` | `/api/optimize-chart` | `chart_api.py` | ✅ | 单图二次优化（异步，只跑优化 agent） |
| `POST` | `/api/complete-viz-code` | `code_api.py` | ✅ | 现有 Python 文件追加可视化代码 |
| `POST` | `/api/data-profile` | `data_api.py` | ✅ | 数据预览 / 图片·PDF 抽表 |
| `GET`  | `/api/data-profile/export` | `data_api.py` | ✅ | 导出预览数据（CSV / ZIP） |
| `POST` | `/api/data-source/db-tables` | `data_api.py` | ✅ | 测试数据库连接并列出表 |
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
| `files` | 条件 | File[] | 上传的数据文件。CSV / Excel / JSON / Parquet / 文档 / **图片 / PDF** 都支持；docx/pptx/xlsx 的内嵌图片也会抽表 |
| `db_config` | 条件 | JSON string | 数据库连接配置（非法 JSON / 不支持的 `type` / sqlite 缺 `database` 直接 `400`）；可选 `tables` 数组或 `query` 自定义 SQL |
| `api_config` | 条件 | JSON string | 外部 API 数据源配置（缺 `url` 且无 `api_type` 直接 `400`） |
| `user_prompt` | 可选 | string | 可视化需求描述 |
| `config` | 可选 | string | 图表配置 JSON（宽高 / 主题 / 配色） |
| `model_url` | 可选 | string | LLM 端点地址（默认走 `.env`） |
| `model_type` | 可选 | string | 模型名 |
| `model_api_key` | 可选 | string | 模型密钥（默认走 `.env`） |
| `mcp_prompt` | 可选 | string | MCP 工具提示 |
| `skill_prompt` | 可选 | string | Skill 提示 |
| `viz_mode` | 可选 | string | `agent` / `auto`（默认，自主流水线）、`legacy` / `chart` / `scientific`（固定 plan 流水线） |
| `multi_table` | 可选 | bool | `true` 时抽出图片 / PDF / Office 内嵌图片里的所有表（默认只取主表） |

> `db_config.query` 只允许单条只读查询（`SELECT` / `WITH` / `SHOW` / `EXPLAIN`）；
> 写操作或多语句（如 `select 1; drop table sales`）在提交阶段直接 `400`，不会进入任务队列。
>
> 图片 / PDF 会先经视觉模型抽成表格，再进入后续 series 拆分与图表生成。
> Word / PPT / Excel 里的表格截图（内嵌图片）在文字层解析失败或退化时也会走视觉模型。
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

`result` 中的主要字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `Charts` | string[] | 图表类型，与 `HtmlFilePaths` 一一对应 |
| `HtmlFilePaths` | string[] | 生成的 HTML 文件名 |
| `AgentLogs` | string[] | 执行日志 |
| `Codes` | string[] | 自包含生成代码，与图表一一对应 |
| `ContextCards` | object[] | 需求 / 数据 / 计划 / 校验 / 产物卡片；含 `assumptions`、`ambiguities` 与生成校验摘要 |

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

### POST /api/optimize-chart

单图二次优化：对**已成功生成**的图表按新指令重渲染（改标题/配色/Top-N/阈值…），
只跑优化 agent，不重跑数据接入与规划。原图与原代码永不覆盖，优化产物登记为
新版本（`<原 plan_id>_optN`），并以 `origin_chart_id` 溯源到原图。

表单字段（`multipart/form-data`）：

| 字段 | 必须 | 说明 |
|------|------|------|
| `chart_id` | 是 | 被优化的图表 HTML 文件名（前端从任务结果/资产列表取） |
| `user_prompt` | 是 | 优化指令（自然语言） |
| `model_url` / `model_type` / `model_api_key` | 否 | 模型配置，与生成接口一致 |

```
202 Accepted
{"task_id": "...", "status": "pending", "conversation_id": "..."}
```

错误：`chart_id` 非法（含路径分隔符）返回 `400`；图表不存在/已被清理返回 `404`。
后续同样用 `GET /api/task/{task_id}` 轮询 / `WS /ws/task/{task_id}` 订阅。

前置条件：生成时已写入图表资产（`runtime/charts/<数据集>/assets.json`）；自备读取
模式（无 series 数据文件）的图表暂不支持优化，任务会以 failed 终止并给出原因。

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

独立于图表生成的数据预览接口：上传文件（或给数据库 / API 配置）后直接返回 schema、
前 10 行预览、列语义角色与推荐图表模式。

#### 表单字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `files` | 条件 | 一个或多个文件（表格 / 文档 / 图片 / PDF；docx/pptx/xlsx 的内嵌图片也会抽表） |
| `db_config` | 条件 | 数据库连接配置 JSON（`type` / `host` / `port` / `user` / `password` / `database`，可带 `tables` / `query`） |
| `api_config` | 条件 | 外部 API 配置 JSON（`url` 或 `api_type`，可带 `method` / `headers` / `params` / `body`） |
| `hint` | 否 | 用户分析意图；图片/PDF/Office 内嵌图片抽表时用于选择主表 |
| `model_url` / `model_api_key` | 否 | 视觉模型凭证（仅多模态抽表需要） |
| `multi_table` | 否 | `1` / `true` 时抽出图片、PDF 页面、Office 内嵌图片中的所有表 |

> `files` / `db_config` / `api_config` 至少提供一种，同时存在时优先 `files`。
> 非法 JSON、未知数据库类型、缺 `database`（sqlite）/ `url`（API）会直接返回 `400`。
> `db_config.query` 同样只允许单条只读查询，写操作 / 多语句返回 `400`。

#### 响应

```json
{
  "profile": {
    "table_name": "sales",
    "row_count": 4,
    "schema": [{"name": "年份", "type": "int64"}],
    "preview": [{"年份": 2023, "销售额": 1200}],
    "series_index": "...",
    "source_kind": "file",
    "session_id": "ds_0123456789ab",
    "exports": [
      {
        "series_id": "sales.城市",
        "name": "城市",
        "axis_kind": "categorical_comparison",
        "csv_url": "/api/data-profile/export?session_id=ds_0123456789ab&series_id=sales.%E5%9F%8E%E5%B8%82"
      }
    ],
    "raw_tables": [
      {
        "index": 0,
        "name": "sales",
        "rows": 4,
        "columns": ["城市", "销售额"],
        "csv_url": "/api/data-profile/export?session_id=ds_0123456789ab&raw=0"
      }
    ],
    "views": [
      {
        "view_id": "vw_9f2c1d3e8a4b6c70",
        "spec_summary": "select 月份, sum(销售额) ... group by 月份 order by 月份",
        "rows": 12,
        "columns": ["月份", "销售额"]
      }
    ]
  },
  "file_count": 1
}
```

图片 / PDF / Office 内嵌图片走视觉模型时**会调用 LLM**；纯表格文件不调用。
Word / PPT / Excel 先走文字层解析，只有解析失败或退化成单列文本时才把内嵌图片交给视觉模型。
图片格式：png / jpg / jpeg / webp / gif / bmp / tif / tiff / avif / heic / heif（HEIC 需 `pillow-heif`）。
`file_count` 是上传文件数；数据库 / API 源为 `0`。

预览产生的 series 会话目录会保留（超过 24 小时后由下一次 `allocate_session_dir` 清理），
便于前端下载：
- `raw_tables[]` 是**归一化后、拆分 series 前**的原始表（抽表结果），用于核对 OCR/表格识别；
- `exports[]` 是拆分后的语义 series，适合直接拿去画图；
- `views[]` 是该会话已物化的派生数据视图（`run_view` 的产物；刚预览完时为空，
  规划 agent 用 `run_view` 补视角后这里会多出对应条目）。

---

### GET /api/data-profile/export

按会话导出 series 或原始表（CSV 带 UTF-8 BOM，Excel 打开中文不乱码）。

| 参数 | 必填 | 说明 |
|------|------|------|
| `session_id` | 是 | `POST /api/data-profile` 返回的 `profile.session_id` |
| `series_id` | 否 | 只导出指定系列；不传则把全部系列打包成 ZIP |
| `raw` | 否 | 导出原始表：`raw=<index>` 单表；`raw=all` 或空值打包全部原始表 |

- 单系列 / 单原始表返回 `text/csv`；不传 id 返回 `application/zip`（每个表一个 `.csv`）。
- `raw` 与 `series_id` 不能同时使用。
- `series_id` 只从会话的 `manifest.json` 查找；原始表只接受 `raw/manifest.json` 里的序号，
  解析后的 parquet 路径必须位于会话目录内；非法/过期会话返回 404，防止路径穿越。
- 会话目录由 `TEMP_DATASETS_DIR` 决定，默认 `runtime/datasets/`。

---

### POST /api/data-source/db-tables

设置面板「测试连接」使用：不保存配置也能验证数据库连接，并列出库里的表，
减少手填表名的拼写错误。

请求支持 `multipart/form-data` 的 `db_config` 字段，或直接提交 JSON body
（`{"db_config": {...}}`，也可以把配置对象本身作为 body）：

```json
{
  "db_config": {
    "type": "MySQL",
    "host": "localhost",
    "port": "3306",
    "user": "root",
    "password": "***",
    "database": "sales"
  }
}
```

成功返回（表名已排序）：

```json
{"db_type": "mysql", "count": 2, "tables": ["orders", "sales"]}
```

- `type` 不区分大小写，`postgres` 会归一化成 `postgresql`；
- 建连超时 5 秒，避免填错主机时前端长时间卡住；
- 配置非法（未知类型、sqlite 文件不存在、JSON 格式错误）返回 `400`；
- 网络不通 / 账号密码错误等连接失败返回 `502`，`detail` 带原始异常；
- **sqlite 只接受已存在的文件**：`sqlite3.connect` 会自动创建空库，这里提前拦截，
  避免把写错的路径悄悄变成一个空数据库。

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
| `VISION_MIN_IMAGE_BYTES` | `4096` | Office 内嵌图片体积下限（字节） |
| `VISION_MIN_IMAGE_SIDE` | `160` | Office 内嵌图片最短边下限（像素） |
| `VISION_MAX_OFFICE_IMAGES` | `8` | docx/pptx/xlsx 单文件最多抽几张图 |
| `VISION_MULTI_TABLE` | `0` | `1` = 一图多表（每张表一条 series） |
| `VISION_MAX_TABLES` | `5` | 一图多表模式下每图最多保留张数 |
| `VISION_CACHE` | `1` | `0` 关闭全部抽表结果缓存（多模态 + 文本） |
| `VISION_CACHE_DIR` | `runtime/cache/vision/` | 多模态抽表缓存目录（内容哈希） |
| `LLM_TEXT_CACHE_DIR` | `runtime/cache/llm_text/` | 文本表格化缓存目录（内容哈希） |
| `VISION_CACHE_TTL_DAYS` | `14` | 抽表缓存保留天数，`0` 不清理 |
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
