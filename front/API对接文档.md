# 前端 API 对接文档

**更新日期：** 2026-07-24
**后端版本：** DataVisualServer Flask API
**前端目录：** `front/src/api/`

---

## 一、接口总览

| # | 方法 | 路径 | 认证 | Content-Type | 异步 | 前端方法 |
|---|------|------|------|--------------|------|---------|
| 1 | POST | `/api/generate-chart-with-prompt` | 是 | multipart/form-data | 是（返回 task_id） | `ApiClient::generate_chart()` |
| 2 | GET | `/api/chart/<chart_id>` | 是 | - | 否 | `ApiClient::chart_url()` |
| 3 | GET | `/api/task/<task_id>` | 是 | - | 否 | `ApiClient::get_task()` |
| 4 | POST | `/api/complete-viz-code` | 是 | JSON | 否（同步） | `ApiClient::complete_viz_code()` |

---

## 二、认证机制

### 后端逻辑
- 环境变量 `SERVICE_API_KEY` 为空时 **不启用认证**，直接放行
- 非空时 **要求认证**，从以下两处任一读取：
  - 请求头 `X-API-Key`
  - 表单字段 `api_key`

### 前端实现
```rust
// 所有请求自动附加 X-API-Key 头
let resp = self.client
    .post(&url)
    .header("X-API-Key", &self.api_key)  // ← 统一认证
    .multipart(form)
    .send().await?;
```

前端通过环境变量 `API_KEY` 初始化：
```rust
let api_key = std::env::var("API_KEY")
    .unwrap_or_else(|_| "datavisual-api-key".to_string());
```

---

## 三、接口详情 + 前端类型映射

### 接口 1：POST /api/generate-chart-with-prompt

**功能：** 上传数据文件 + 用户提示词，异步提交图表生成任务。

#### 请求（multipart/form-data）

| 字段 | 类型 | 必填 | 默认值 | 前端类型 |
|------|------|------|--------|---------|
| `files` | File[] | 与 db_config 二选一 | - | `request.file_paths: Vec<String>` |
| `user_prompt` | string | 是 | `""` | `request.user_prompt: String` |
| `viz_mode` | string | 否 | `"auto"` | `request.viz_mode: VizMode` |
| `db_config` | string(JSON) | 否 | - | `request.db_config: Option<String>` |
| `model_url` | string | 否 | - | `request.model_url: Option<String>` |
| `model_type` | string | 否 | - | `request.model_type: Option<String>` |
| `model_api_key` | string | 否 | - | `request.model_api_key: Option<String>` |
| `mcp_prompt` | string | 否 | `""` | `request.mcp_prompt: Option<String>` |
| `skill_prompt` | string | 否 | `""` | `request.skill_prompt: Option<String>` |
| `config` | string | 否 | - | *未映射（前端暂不支持）* |

**viz_mode 枚举值：** `auto` / `chart` / `scientific`

#### 响应

| 状态码 | 响应体 | 前端类型 |
|--------|--------|---------|
| 202 | `{"task_id": "...", "status": "pending"}` | `GenerateChartResponse` |
| 400 | `{"detail": "错误描述"}` | `ErrorResponse` |
| 401 | `{"detail": "Invalid or missing API key"}` | `ErrorResponse` |
| 500 | `{"detail": "异常信息"}` | `ErrorResponse` |

#### 前端类型定义（`src/api/types.rs`）

```rust
pub struct GenerateChartRequest {
    pub file_paths: Vec<String>,
    pub user_prompt: String,
    pub viz_mode: VizMode,
    pub db_config: Option<String>,
    pub model_url: Option<String>,
    pub model_type: Option<String>,
    pub model_api_key: Option<String>,
    pub mcp_prompt: Option<String>,
    pub skill_prompt: Option<String>,
}

pub struct GenerateChartResponse {
    pub task_id: String,
    pub status: String,
}
```

#### 前端调用示例

```rust
let request = GenerateChartRequest {
    file_paths: vec!["C:/data/sales.xlsx".to_string()],
    user_prompt: "画一个柱状图展示销售趋势".to_string(),
    viz_mode: VizMode::Auto,
    db_config: None,
    model_url: None, model_type: None, model_api_key: None,
    mcp_prompt: None, skill_prompt: None,
};

let resp = client.generate_chart(&request).await?;
// resp.task_id = "a1b2c3d4..."
```

---

### 接口 2：GET /api/chart/<chart_id>

**功能：** 获取已生成图表的 HTML 文件。

#### 请求

| 参数 | 位置 | 说明 |
|------|------|------|
| `chart_id` | path | 图表文件名（如 `chart_20260709_1.html`） |
| `X-API-Key` | header | 认证密钥 |

**安全校验：** `chart_id` 不允许包含 `/`、`\`、`..`

#### 响应

| 状态码 | 响应体 | 说明 |
|--------|--------|------|
| 200 | HTML 文件内容 | `Content-Type: text/html` |
| 400 | `{"detail": "Invalid chart ID"}` | 非法 chart_id |
| 401 | `{"detail": "..."}` | 未认证 |
| 404 | `{"detail": "Chart not found"}` | 图表不存在 |

#### 前端实现

```rust
// 直接构建 URL，用浏览器/WebView2 加载
pub fn chart_url(&self, chart_id: &str) -> String {
    format!("{}/api/chart/{}", self.base_url, chart_id)
}

// 使用方式
let url = client.chart_url("chart_20260709_1.html");
components::webview::open_url(&url);  // 用浏览器打开
```

---

### 接口 3：GET /api/task/<task_id>

**功能：** 查询异步任务状态。

#### 请求

| 参数 | 位置 | 说明 |
|------|------|------|
| `task_id` | path | 接口 1 返回的 task_id |
| `X-API-Key` | header | 认证密钥 |

#### 响应（200 OK）

```json
{
  "task_id": "a1b2c3d4...",
  "status": "success",
  "result": {
    "Charts": ["Bar", "Line"],
    "HtmlFilePaths": ["chart_1.html", "chart_2.html"],
    "AgentLogs": ["..."]
  },
  "error": null,
  "raw": {
    "successful_charts": [...],
    "failed_plans": [...]
  },
  "created_at": "..."
}
```

**status 枚举值：** `pending` / `running` / `success` / `failed`

#### 前端类型定义（`src/api/types.rs`）

```rust
pub enum TaskStatus {
    Pending, Running, Succeeded, Failed,
}

pub struct TaskResponse {
    pub task_id: String,
    pub status: TaskStatus,
    pub result: Option<TaskResult>,
    pub error: Option<String>,
}

pub struct TaskResult {
    pub charts: Option<Vec<ChartInfo>>,
    pub report_path: Option<String>,
}

pub struct ChartInfo {
    pub chart_id: String,
    pub title: Option<String>,
    pub chart_type: Option<String>,
}
```

> **注意：** 后端 `result` 实际结构为 `{Charts, HtmlFilePaths, AgentLogs}`，前端 `TaskResult` 做了简化映射。`HtmlFilePaths` 中的文件名即为 `chart_id`，可用于接口 2 获取 HTML。

#### 前端轮询示例

```rust
// 提交任务
let resp = client.generate_chart(&request).await?;
let task_id = resp.task_id;

// 轮询直到完成（每秒一次，5分钟超时）
let task = client.poll_task_until_done(&task_id).await?;

// 获取图表 URL
if let Some(result) = task.result {
    if let Some(charts) = result.charts {
        for chart in charts {
            let url = client.chart_url(&chart.chart_id);
            components::webview::open_url(&url);
        }
    }
}
```

---

### 接口 4：POST /api/complete-viz-code

**功能：** 可视化代码补全（同步执行）。

#### 请求（JSON）

| 字段 | 类型 | 必填 | 前端类型 |
|------|------|------|---------|
| `code_file_paths` | string[] | 是 | `request.code_file_paths: Vec<String>` |
| `user_prompt` | string | 是 | `request.user_prompt: String` |
| `scientific_lib` | string | 否 | `request.scientific_lib: Option<String>` |
| `model_url` | string | 否 | `request.model_url: Option<String>` |
| `model_type` | string | 否 | `request.model_type: Option<String>` |
| `model_api_key` | string | 否 | `request.model_api_key: Option<String>` |

**scientific_lib 枚举值：** `matplotlib` / `plotly` / `seaborn` / `auto`

#### 前端类型定义（`src/api/types.rs`）

```rust
pub struct CompleteVizCodeRequest {
    pub code_file_paths: Vec<String>,
    pub user_prompt: String,
    pub scientific_lib: Option<String>,
    pub model_url: Option<String>,
    pub model_type: Option<String>,
    pub model_api_key: Option<String>,
}

pub struct CompleteVizCodeResponse {
    pub snippet: String,
    pub explanation: String,
    pub libs: Vec<String>,
}
```

---

## 四、前端类型与后端模型对照表

| 后端模型（Python） | 前端类型（Rust） | 文件位置 |
|-------------------|-----------------|---------|
| `GenerateChartWithPromptRequest` | `GenerateChartRequest` | `src/api/types.rs` |
| `GenerateChartWithPromptResponse` | `GenerateChartResponse` + `TaskResult` | `src/api/types.rs` |
| `CompleteVizCodeRequest` | `CompleteVizCodeRequest` | `src/api/types.rs` |
| `ErrorResponse` | `ErrorResponse` | `src/api/types.rs` |
| `GetChartRequest` | 直接用 path param | - |
| - | `TaskStatus` / `TaskResponse` / `ChartInfo` | `src/api/types.rs` |
| - | `VizMode` | `src/api/types.rs` |

---

## 五、完整数据流

```
用户操作                    前端                         后端
─────────────────────────────────────────────────────────────
选择文件                pick_files()
                         ↓
输入提示词              编辑框
                         ↓
点击"生成图表"          on_generate()
                         ↓
                        generate_chart()  ──POST──→  /api/generate-chart-with-prompt
                                                          ↓
                         ←──202 {task_id}──────────  异步执行中
                         ↓
                        poll_task_until_done() ──GET──→ /api/task/<task_id>
                                                          ↓
                         ←──200 {status: running}────  生成中...
                         ↓
                         (每秒轮询)
                         ↓
                         ←──200 {status: success}────  完成
                              {result: {Charts, HtmlFilePaths}}
                         ↓
                        chart_url()         ──GET──→  /api/chart/<chart_id>
                                                          ↓
                         ←──200 HTML─────────────────  返回图表
                         ↓
                        open_url() / WebView2
                         ↓
                    浏览器/WebView 展示图表
```

---

## 六、错误处理

### 前端统一错误处理策略

| HTTP 状态码 | 含义 | 前端处理 |
|-------------|------|---------|
| 200/202 | 成功 | 解析 JSON 响应 |
| 400 | 参数错误 | 显示 `detail` 错误信息 |
| 401 | 未认证 | 提示用户检查 API Key |
| 404 | 不存在 | 提示资源不存在 |
| 500 | 服务器错误 | 显示错误详情，建议重试 |

### 前端错误处理代码

```rust
let status = resp.status();
let body = resp.text().await.unwrap_or_default();

if status == StatusCode::ACCEPTED || status == StatusCode::OK {
    // 成功：解析 JSON
    serde_json::from_str(&body)?
} else if status == StatusCode::UNAUTHORIZED {
    // 401：提示检查 API Key
    Err("API Key 无效，请检查配置".into())
} else {
    // 其他错误：尝试解析 ErrorResponse
    let err: ErrorResponse = serde_json::from_str(&body)?;
    Err(err.detail)
}
```

---

## 七、环境变量配置

| 环境变量 | 前端用途 | 默认值 |
|---------|---------|--------|
| `BACKEND_URL` | 后端地址 | `http://localhost:5000` |
| `API_KEY` | 认证密钥（对应后端 `SERVICE_API_KEY`） | `datavisual-api-key` |

---

## 八、后端数据模型补充说明

### 后端 `result` 字段实际结构

后端 `GenerateChartWithPromptResponse` 的实际字段：

```python
class GenerateChartWithPromptResponse(BaseModel):
    Charts: List[str]          # 图表类型列表，如 ["Bar", "Line"]
    HtmlFilePaths: List[str]   # HTML 文件名列表，如 ["chart_1.html", "chart_2.html"]
    AgentLogs: List[str]       # Agent 日志列表
```

前端 `TaskResult` 做了简化映射：
- `Charts` -> `charts: Vec<ChartInfo>`（前端额外解析出 chart_id）
- `HtmlFilePaths` -> 用于 `chart_url()` 构建访问 URL
- `AgentLogs` -> 前端暂不处理

### 后端 `raw` 字段

```json
{
  "successful_charts": [
    {"chart_type": "Bar", "chart_path": "chart_1.html", ...}
  ],
  "failed_plans": [
    {"plan_id": "2", "error": "..."}
  ]
}
```

前端暂不解析 `raw` 字段，仅使用 `result` 中的结构化数据。

---

## 九、待对接项

| 项目 | 状态 | 说明 |
|------|------|------|
| 图表生成 | ✅ 已对接 | `generate_chart()` |
| 任务轮询 | ✅ 已对接 | `poll_task_until_done()` |
| 图表查看 | ✅ 已对接 | `chart_url()` + `open_url()` |
| 代码补全 | ✅ 已对接 | `complete_viz_code()` |
| `config` 参数 | ❌ 未对接 | 图表配置 JSON，前端暂不支持 |
| `db_config` 参数 | ⚠️ 部分对接 | 类型已定义，UI 未提供输入 |
| WebView2 嵌入 | ⏳ 预留接口 | 当前用 `open_url()` 浏览器替代 |
| 任务轮询 UI 更新 | ⏳ 待实现 | `on_generate` 中需添加轮询回调更新状态文本 |
