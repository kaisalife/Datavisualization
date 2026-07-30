/// HTTP 客户端封装
///
/// 封装 reqwest，提供与 DataVisualServer 后端交互的方法。
/// 所有方法都是 async，需在 tokio 运行时中调用。
/// 错误处理：根据 HTTP 状态码返回分级错误信息。

use std::path::Path;
use std::time::Duration;

use anyhow::{Context, Result};
use reqwest::{Client, StatusCode};

use super::types::*;

/// 后端 API 客户端
#[derive(Clone)]
pub struct ApiClient {
    client: Client,
    base_url: String,
    api_key: String,
}

/// 根据 HTTP 状态码和响应体生成分级错误信息
///
/// - 400: 参数错误（显示后端 detail）
/// - 401: 认证失败（提示检查 API Key）
/// - 404: 资源不存在
/// - 500: 服务器错误
fn format_http_error(status: StatusCode, body: &str) -> String {
    // 尝试从响应体中解析 ErrorResponse
    let detail = serde_json::from_str::<ErrorResponse>(body)
        .map(|e| e.detail)
        .unwrap_or_else(|_| body.to_string());

    match status {
        StatusCode::BAD_REQUEST => format!("参数错误: {}", detail),
        StatusCode::UNAUTHORIZED => format!("认证失败（请检查 API Key）: {}", detail),
        StatusCode::NOT_FOUND => format!("资源不存在: {}", detail),
        StatusCode::INTERNAL_SERVER_ERROR => format!("服务器错误: {}", detail),
        _ => format!("后端返回错误 {}: {}", status, detail),
    }
}

impl ApiClient {
    /// 创建新的 API 客户端
    pub fn new(base_url: &str, api_key: &str) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(300))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            client,
            base_url: base_url.trim_end_matches('/').to_string(),
            api_key: api_key.to_string(),
        }
    }

    /// 提交图表生成任务
    ///
    /// 成功返回 GenerateChartResponse（含 task_id）。
    /// 错误返回分级信息：
    /// - 400: 参数错误（如缺少 files/db_config）
    /// - 401: API Key 无效
    /// - 500: 服务器内部错误
    pub async fn generate_chart(
        &self,
        request: &GenerateChartRequest,
    ) -> Result<GenerateChartResponse> {
        let url = format!("{}/api/generate-chart-with-prompt", self.base_url);

        let mut form = reqwest::multipart::Form::new()
            .text("user_prompt", request.user_prompt.clone())
            .text("viz_mode", request.viz_mode.as_str().to_string());

        if let Some(db_config) = &request.db_config {
            form = form.text("db_config", db_config.clone());
        }
        if let Some(config) = &request.config {
            form = form.text("config", config.clone());
        }
        if let Some(model_url) = &request.model_url {
            form = form.text("model_url", model_url.clone());
        }
        if let Some(model_type) = &request.model_type {
            form = form.text("model_type", model_type.clone());
        }
        if let Some(model_api_key) = &request.model_api_key {
            form = form.text("model_api_key", model_api_key.clone());
        }
        if let Some(mcp_prompt) = &request.mcp_prompt {
            form = form.text("mcp_prompt", mcp_prompt.clone());
        }
        if let Some(skill_prompt) = &request.skill_prompt {
            form = form.text("skill_prompt", skill_prompt.clone());
        }

        for file_path in &request.file_paths {
            let path = Path::new(file_path);
            if !path.exists() {
                anyhow::bail!("文件不存在: {}", file_path);
            }
            let filename = path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("file");

            // 流式读取文件，避免大文件全部读入内存
            let file = tokio::fs::File::open(file_path)
                .await
                .context(format!("读取文件失败: {}", file_path))?;
            let size = file.metadata().await.map(|m| m.len()).unwrap_or(0);
            let stream = tokio_util::io::ReaderStream::new(file);
            let body = reqwest::Body::wrap_stream(stream);
            let part = reqwest::multipart::Part::stream_with_length(body, size)
                .file_name(filename.to_string());
            form = form.part("files", part);
        }

        let resp = self
            .client
            .post(&url)
            .header("X-API-Key", &self.api_key)
            .multipart(form)
            .send()
            .await
            .context("网络请求失败（后端是否已启动？）")?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if status == StatusCode::ACCEPTED || status == StatusCode::OK {
            serde_json::from_str::<GenerateChartResponse>(&body)
                .context(format!("解析响应失败: {}", body))
        } else {
            anyhow::bail!(format_http_error(status, &body))
        }
    }

    /// 查询任务状态
    ///
    /// 错误返回分级信息：
    /// - 401: API Key 无效
    /// - 404: 任务不存在
    /// - 500: 服务器内部错误
    pub async fn get_task(&self, task_id: &str) -> Result<TaskResponse> {
        let url = format!("{}/api/task/{}", self.base_url, task_id);

        let resp = self
            .client
            .get(&url)
            .header("X-API-Key", &self.api_key)
            .send()
            .await
            .context("网络请求失败（后端是否已启动？）")?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if status == StatusCode::OK {
            serde_json::from_str::<TaskResponse>(&body)
                .context(format!("解析响应失败: {}", body))
        } else {
            anyhow::bail!(format_http_error(status, &body))
        }
    }

    /// 轮询任务直到完成（或超时）
    ///
    /// 每秒轮询一次，最多等待 5 分钟。
    /// 每 5 秒调用 on_progress 回调（传入已等待秒数）。
    /// 成功返回 TaskResponse（含 result）。
    /// 失败返回任务错误信息或超时。
    pub async fn poll_task_until_done<F>(
        &self,
        task_id: &str,
        on_progress: F,
    ) -> Result<TaskResponse>
    where
        F: Fn(u64),
    {
        let max_attempts = 300; // 5 分钟
        for i in 0..max_attempts {
            let task = match self.get_task(task_id).await {
                Ok(task) => task,
                Err(e) => {
                    if i % 5 == 0 {
                        tracing::warn!("查询任务失败，继续重试: {}", e);
                    }
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    continue;
                }
            };
            match task.status {
                TaskStatus::Success => return Ok(task),
                TaskStatus::Failed => {
                    anyhow::bail!("任务失败: {}", task.error.unwrap_or_default())
                }
                TaskStatus::Cancelled => {
                    anyhow::bail!("任务已取消")
                }
                _ => {
                    if i % 5 == 0 && i > 0 {
                        on_progress(i);
                    }
                    tokio::time::sleep(Duration::from_secs(1)).await;
                }
            }
        }
        anyhow::bail!("任务超时（5 分钟）")
    }

    /// 获取图表 HTML 的 URL
    ///
    /// 返回可直接在浏览器/WebView2 中加载的 URL。
    pub fn chart_url(&self, chart_id: &str) -> String {
        format!("{}/api/chart/{}", self.base_url, chart_id)
    }

    /// 提交代码可视化补全
    ///
    /// 错误返回分级信息：
    /// - 400: code_file_paths 为空
    /// - 401: API Key 无效
    /// - 500: 服务器内部错误
    pub async fn complete_viz_code(
        &self,
        request: &CompleteVizCodeRequest,
    ) -> Result<CompleteVizCodeResponse> {
        let url = format!("{}/api/complete-viz-code", self.base_url);

        let resp = self
            .client
            .post(&url)
            .header("X-API-Key", &self.api_key)
            .json(request)
            .send()
            .await
            .context("网络请求失败（后端是否已启动？）")?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if status.is_success() {
            serde_json::from_str::<CompleteVizCodeResponse>(&body)
                .context(format!("解析响应失败: {}", body))
        } else {
            anyhow::bail!(format_http_error(status, &body))
        }
    }

    // ============================================================
    // 对话日志 CRUD
    // ============================================================

    /// 列出对话（分页）
    pub async fn list_conversations(&self, limit: u32, offset: u32) -> Result<ConversationListResponse> {
        let url = format!("{}/api/conversations?limit={}&offset={}", self.base_url, limit, offset);

        let resp = self
            .client
            .get(&url)
            .header("X-API-Key", &self.api_key)
            .send()
            .await
            .context("网络请求失败")?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if status.is_success() {
            serde_json::from_str::<ConversationListResponse>(&body)
                .context(format!("解析响应失败: {}", body))
        } else {
            anyhow::bail!(format_http_error(status, &body))
        }
    }

    /// 获取对话详情
    pub async fn get_conversation(&self, conversation_id: &str) -> Result<ConversationDetail> {
        let url = format!("{}/api/conversations/{}", self.base_url, conversation_id);

        let resp = self
            .client
            .get(&url)
            .header("X-API-Key", &self.api_key)
            .send()
            .await
            .context("网络请求失败")?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if status.is_success() {
            serde_json::from_str::<ConversationDetail>(&body)
                .context(format!("解析响应失败: {}", body))
        } else {
            anyhow::bail!(format_http_error(status, &body))
        }
    }

    /// 删除对话
    pub async fn delete_conversation(&self, conversation_id: &str) -> Result<()> {
        let url = format!("{}/api/conversations/{}", self.base_url, conversation_id);

        let resp = self
            .client
            .delete(&url)
            .header("X-API-Key", &self.api_key)
            .send()
            .await
            .context("网络请求失败")?;

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!(format_http_error(status, &body))
        }
        Ok(())
    }

    /// 修改提示词
    pub async fn update_prompt(&self, conversation_id: &str, new_prompt: &str) -> Result<()> {
        let url = format!("{}/api/conversations/{}/prompt", self.base_url, conversation_id);

        let body = serde_json::json!({"user_prompt": new_prompt});
        let resp = self
            .client
            .put(&url)
            .header("X-API-Key", &self.api_key)
            .json(&body)
            .send()
            .await
            .context("网络请求失败")?;

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!(format_http_error(status, &body))
        }
        Ok(())
    }

    /// 构建 WebSocket URL
    pub fn ws_task_url(&self, task_id: &str) -> String {
        let ws_base = self.base_url.replace("http://", "ws://").replace("https://", "wss://");
        format!("{}/ws/task/{}", ws_base, task_id)
    }

    /// 获取 base_url（公开方法）
    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    /// 获取 api_key（公开方法，供 WebSocket 等需要自行构造请求头的场景使用）
    pub fn api_key(&self) -> &str {
        &self.api_key
    }

    /// 发送简单的 POST 请求（无 body）
    pub async fn raw_post(&self, url: &str) -> Result<()> {
        let resp = self
            .client
            .post(url)
            .header("X-API-Key", &self.api_key)
            .send()
            .await
            .context("网络请求失败")?;

        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            anyhow::bail!(format_http_error(status, &body))
        }
        Ok(())
    }
}
