use crate::api;

/// 格式化对话详情为可读文本
pub(crate) fn format_conversation_detail(detail: &api::types::ConversationDetail) -> String {
    let mut lines = Vec::new();
    lines.push("=== 对话详情 ===".to_string());
    lines.push(format!("ID: {}", detail.conversation_id));
    lines.push(format!("状态: {}", detail.status.as_deref().unwrap_or("?")));
    lines.push(format!("创建时间: {}", detail.created_at));
    lines.push(format!("可视化模式: {}", detail.viz_mode.as_deref().unwrap_or("?")));
    lines.push(format!("提示词: {}", detail.user_prompt));
    if let Some(logs) = &detail.agent_logs {
        lines.push("Agent 日志:".to_string());
        for log in logs {
            lines.push(format!("  - {}", log));
        }
    }
    if let Some(files) = &detail.html_file_paths {
        lines.push("图表文件:".to_string());
        for f in files {
            lines.push(format!("  - {}", f));
        }
    }
    if let Some(charts) = &detail.charts {
        if !charts.is_empty() {
            lines.push(format!("图表类型: {}", charts.join(", ")));
        }
    }
    if let Some(err) = &detail.error {
        lines.push(format!("错误: {}", err));
    }
    lines.join("\n")
}

/// 同步连接 WebSocket 并等待任务完成通知
pub(crate) fn connect_websocket_blocking(
    ws_url: &str,
    api_key: &str,
) -> std::result::Result<api::types::TaskCompleteNotification, String> {
    use tungstenite::client::IntoClientRequest;
    let mut request = ws_url
        .into_client_request()
        .map_err(|e| format!("构建 WebSocket 请求失败: {}", e))?;
    request
        .headers_mut()
        .insert("X-API-Key", api_key.parse().map_err(|e| format!("无效 API Key: {}", e))?);
    let (mut socket, _) =
        tungstenite::connect(request).map_err(|e| format!("WebSocket 连接失败: {}", e))?;
    loop {
        match socket.read() {
            Ok(tungstenite::Message::Text(text)) => {
                // 解析通知；仅终态（success/failed/cancelled）返回，忽略 running/pending 中间态
                match serde_json::from_str::<api::types::TaskCompleteNotification>(&text) {
                    Ok(notif) => {
                        let is_terminal = matches!(
                            notif.status.as_str(),
                            "success" | "failed" | "cancelled"
                        );
                        if is_terminal {
                            return Ok(notif);
                        }
                        // 非终态，继续等待
                    }
                    Err(_) => continue,
                }
            }
            Ok(tungstenite::Message::Close(_)) => return Err("WebSocket 连接已关闭".to_string()),
            Ok(_) => continue,
            Err(e) => return Err(format!("WebSocket 读取错误: {}", e)),
        }
    }
}

/// 从完整路径提取文件名
pub(crate) fn filename_from_path(path: &str) -> String {
    std::path::Path::new(path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("file")
        .to_string()
}

/// 获取文件扩展名（小写，无点）
pub(crate) fn filename_ext(path: &str) -> String {
    std::path::Path::new(path)
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase()
}

/// 空字符串转 None
pub(crate) fn opt_string(s: String) -> Option<String> {
    if s.trim().is_empty() {
        None
    } else {
        Some(s)
    }
}
