# API 总览

本目录是 DataVisualServer 后端所有功能接口的归档与模块化拆分。

## 目录结构

```
api/
├── __init__.py        # 蓝图总导出
├── common.py          # 共享依赖（executor/tasks 状态、API Key 校验）
├── chart_api.py       # 图表生成模块
├── task_api.py        # 任务状态查询
└── code_api.py        # 可视化代码补全
```

## 所有接口一览

| 方法 | 路径 | 所属模块 | 简介 |
|------|------|----------|------|
| `POST` | `/api/generate-chart-with-prompt` | `chart_api.py` | 提交图表生成任务（异步） |
| `GET`  | `/api/task/<task_id>`              | `task_api.py`  | 查询任务进度 / 结果 |
| `GET`  | `/api/chart/<chart_id>`            | `chart_api.py` | 获取生成的图表 HTML |
| `POST` | `/api/complete-viz-code`           | `code_api.py`  | 现有 Python 文件追加可视化代码 |

---

### POST /api/generate-chart-with-prompt

提交可视化任务（支持文件数据源 或 数据库源）。支持 `multipart/form-data` 与
`application/x-www-form-urlencoded` 两种 Content-Type。

#### 表单字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `files` | 条件 | File[] | 上传的 Excel/CSV 等文件。必须 files 与 db_config 二选一 |
| `db_config` | 条件 | JSON string | 数据库连接配置（JSON 字符串）。必须 files 与 db_config 二选一 |
| `user_prompt` | 可选 | string | 用户自定义可视化需求描述 |
| `config` | 可选 | string | 额外 JSON 配置 |
| `model_url` | 可选 | string | LLM 端点地址（默认走 .env 配置） |
| `model_type` | 可选 | string | 模型类型（如 kimi2.5 / gpt-4o） |
| `model_api_key` | 可选 | string | 模型密钥（默认走 .env 配置） |
| `mcp_prompt` | 可选 | string | MCP 工具提示 |
| `skill_prompt` | 可选 | string | Skill 提示 |
| `viz_mode` | 可选 | string | 可视化模式（auto / file_only / db_only），默认 `auto` |

#### 响应

```
202 Accepted
{
  "task_id": "abc123...",
  "status": "pending"
}
```

后续用 `GET /api/task/{task_id}` 轮询结果。

#### 鉴权

若 `SERVICE_API_KEY` 环境变量已设置，需在请求头：
```
X-API-Key: <your_key>
```
或在表单字段 `api_key` 中传递。

---

### GET /api/task/{task_id}

查询异步任务状态。

#### 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |
| `status` | string | pending / running / success / failed |
| `result` | object | 成功时有值（与 GenerateChartWithPromptResponse 一致） |
| `error` | string | 失败时有值 |
| `raw` | object | 完整 successful_charts / failed_plans 列表 |

---

### GET /api/chart/{chart_id}

获取已生成图表的 HTML 文件。

#### 参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `chart_id` | string | 路径最后一段的文件名，如 `chart_1_20260718_130443.html` |

#### 安全

已做路径穿越防护（拒绝 `/`、`\`、`..`）。

#### 路径兼容

先在 `CHARTS_DIR/chart_id` 直接查找；若不存在则 `rglob` 递归查找（兼容旧版结构 `charts/xxx/charts/*.html`）。

---

### POST /api/complete-viz-code

在已有的 Python 代码末尾追加可视化代码片段（常用于科学计算 / 数据分析脚本）。

#### 请求体

支持两种格式：

1. **application/json**
   ```json
   {
     "code_file_paths": ["d:/project/a.py", "d:/project/b.py"],
     "user_prompt": "画一个柱状图展示各列的统计值",
     "scientific_lib": "matplotlib",
     "model_url": "...",
     "model_type": "...",
     "model_api_key": "..."
   }
   ```

2. **multipart/form-data**
   - `code_files`：上传 .py 文件列表
   - `code_file_paths`：已上传到服务器的路径列表（分号 / 换行分隔）
   - 其余字段与 json 方式一致

#### 响应

```
200 OK
{
  "snippet": "import matplotlib.pyplot as plt\n...",
  "explanation": "...",
  "libs": ["matplotlib", "numpy"]
}
```

---

## 环境变量（影响 API 行为）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LOG_PATH` | `logs/datavisual.jsonl` | 结构化日志输出文件（JSON Lines） |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `MAX_CONTENT_LENGTH` | `52428800` (50MB) | 单次请求 Body 上限 |
| `TEMP_UPLOAD_DIR` | `temp_uploads/` | 文件上传暂存目录 |
| `CHARTS_DIR` | `charts/` | 图表产物输出目录 |
| `SERVICE_API_KEY` | "" | API 调用鉴权密钥（可选） |
| `TASK_MAX_WORKERS` | `2` | 异步任务并发度（ThreadPoolExecutor） |
| `FLASK_HOST` | `0.0.0.0` | 监听地址 |
| `FLASK_PORT` | `5000` | 监听端口 |
| `FLASK_DEBUG` | `false` | 是否开启 Flask debug 模式 |

---

## 错误响应格式

所有接口遇到错误时统一返回：

```json
{
  "detail": "错误描述文字"
}
```

| HTTP 码 | 典型场景 |
|---------|----------|
| `400` | 参数缺失、db_config JSON 解析失败、路径非法 |
| `401` | API Key 校验不通过 |
| `404` | task 不存在、chart 文件不存在 |
| `500` | 内部异常（ServiceError / ConfigError / 未预期 Exception） |

---

## 扩展与维护

需要新增接口时：

1. 在对应模块的 `*_api.py` 里加路由；若为新领域新增 `xxx_api.py` + Blueprint
2. 在 `api/__init__.py` 导出新 Blueprint
3. 在 `app.py` 中 `app.register_blueprint(...)` 注册
4. 在本表追加文档行

共享依赖（全局线程池、任务状态、logger 等）统一在 `api/common.py` 中通过
`flask.current_app.config["KEY"]` 访问，不跨模块直接 import 全局变量。
