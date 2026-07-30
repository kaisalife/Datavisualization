/// API 请求/响应类型定义
///
/// 与后端 Entity/ApiModels.py 和 api/*.py 的数据模型一一对应。
/// 后端字段名首字母大写（PascalCase），用 #[serde(rename)] 映射。

use serde::{Deserialize, Serialize};

// ============================================================
// 通用
// ============================================================

/// 错误响应（后端 ErrorResponse）
#[derive(Debug, Clone, Deserialize)]
pub struct ErrorResponse {
    pub detail: String,
}

// ============================================================
// 图表生成 API
// ============================================================

/// 图表生成请求（对应后端 multipart form）
#[derive(Debug, Clone)]
pub struct GenerateChartRequest {
    /// 要上传的文件路径列表
    pub file_paths: Vec<String>,
    /// 用户提示词
    pub user_prompt: String,
    /// 可视化模式
    pub viz_mode: VizMode,
    /// 数据库配置（JSON string，可选）
    pub db_config: Option<String>,
    /// 图表配置（JSON string，可选）
    pub config: Option<String>,
    /// 模型 URL（可选，覆盖默认）
    pub model_url: Option<String>,
    /// 模型类型
    pub model_type: Option<String>,
    /// 模型 API Key
    pub model_api_key: Option<String>,
    /// MCP 提示词
    pub mcp_prompt: Option<String>,
    /// 技能提示词
    pub skill_prompt: Option<String>,
}

/// 可视化模式
#[derive(Debug, Clone, Default)]
pub enum VizMode {
    #[default]
    Auto,
    Chart,
    Scientific,
}

impl VizMode {
    pub fn as_str(&self) -> &str {
        match self {
            VizMode::Auto => "auto",
            VizMode::Chart => "chart",
            VizMode::Scientific => "scientific",
        }
    }
}

/// 图表生成响应（202 Accepted）
#[derive(Debug, Clone, Deserialize)]
pub struct GenerateChartResponse {
    pub task_id: String,
    pub status: String,
}

// ============================================================
// 任务状态 API
// ============================================================

/// 任务状态
///
/// 后端返回值为小写：`pending` / `running` / `success` / `failed` / `cancelled`
/// 注意：后端是 `success` 不是 `succeeded`
#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TaskStatus {
    Pending,
    Running,
    Success,
    Failed,
    Cancelled,
}

/// 任务查询响应
#[derive(Debug, Clone, Deserialize)]
pub struct TaskResponse {
    pub task_id: String,
    pub status: TaskStatus,
    /// 成功时为 GenerateChartWithPromptResponse 的序列化结果
    pub result: Option<TaskResult>,
    /// 失败时为错误信息
    pub error: Option<String>,
}

/// 任务结果（对应后端 GenerateChartWithPromptResponse）
///
/// 后端字段名是 PascalCase，用 #[serde(rename)] 映射。
#[derive(Debug, Clone, Deserialize)]
pub struct TaskResult {
    /// 图表类型列表，如 ["Bar", "Line"]
    #[serde(rename = "Charts", default)]
    pub charts: Vec<String>,
    /// HTML 文件名列表，如 ["chart_1.html", "chart_2.html"]
    /// 文件名即为 chart_id，可直接用于 GET /api/chart/<chart_id>
    #[serde(rename = "HtmlFilePaths", default)]
    pub html_file_paths: Vec<String>,
    /// Agent 日志列表
    #[serde(rename = "AgentLogs", default)]
    pub agent_logs: Vec<String>,
}

// ============================================================
// 代码补全 API
// ============================================================

/// 代码补全请求
#[derive(Debug, Clone, Serialize)]
pub struct CompleteVizCodeRequest {
    pub code_file_paths: Vec<String>,
    pub user_prompt: String,
    pub scientific_lib: Option<String>,
    pub model_url: Option<String>,
    pub model_type: Option<String>,
    pub model_api_key: Option<String>,
}

/// 代码补全响应
#[derive(Debug, Clone, Deserialize)]
pub struct CompleteVizCodeResponse {
    pub snippet: String,
    pub explanation: String,
    pub libs: Vec<String>,
}

// ============================================================
// 对话日志 API
// ============================================================

/// 对话摘要（列表项）
#[derive(Debug, Clone, Deserialize)]
pub struct ConversationSummary {
    pub conversation_id: String,
    pub task_id: Option<String>,
    pub user_prompt: String,
    pub viz_mode: Option<String>,
    pub status: Option<String>,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// 对话列表响应
#[derive(Debug, Clone, Deserialize)]
pub struct ConversationListResponse {
    pub conversations: Vec<ConversationSummary>,
    pub total: usize,
}

/// 对话详情
#[derive(Debug, Clone, Deserialize)]
pub struct ConversationDetail {
    pub conversation_id: String,
    pub task_id: Option<String>,
    pub user_prompt: String,
    pub file_paths: Option<Vec<String>>,
    pub viz_mode: Option<String>,
    pub db_config: Option<String>,
    pub status: Option<String>,
    pub agent_logs: Option<Vec<String>>,
    pub charts: Option<Vec<String>>,
    pub html_file_paths: Option<Vec<String>>,
    pub error: Option<String>,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// WebSocket 任务完成通知
#[derive(Debug, Clone, Deserialize)]
pub struct TaskCompleteNotification {
    pub status: String,
    pub result: Option<TaskResult>,
    pub error: Option<String>,
}
