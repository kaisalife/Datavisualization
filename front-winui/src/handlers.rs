use winio::prelude::*;
use crate::api;
use crate::bridge::BridgeMessage;
use crate::messages::MainMessage;
use crate::state::AppMode;
use crate::runtime::tokio_handle;
use crate::helpers::{format_conversation_detail, connect_websocket_blocking, filename_from_path, opt_string};
use crate::{Error, MainModel};

impl MainModel {
    /// 桥接消息分发
    pub(crate) async fn handle_bridge_action(
        &mut self,
        msg: BridgeMessage,
        sender: &ComponentSender<MainModel>,
    ) -> std::result::Result<bool, Error> {
        println!("[Bridge] 分发 action: {}", msg.action);
        match msg.action.as_str() {
            "sendPrompt" => self.handle_send_prompt(msg.data, sender),
            "cancelTask" => self.handle_cancel_task(sender),
            "newChat" => self.handle_new_chat(),
            "loadHistory" => self.handle_load_history(sender),
            "viewDetail" => self.handle_view_detail(msg.data, sender),
            "deleteConversation" => self.handle_delete_conversation(msg.data, sender),
            "openFolder" => self.handle_open_folder().await,
            "attachFile" => self.handle_attach_file().await,
            "selectDb" => self.handle_select_db(msg.data),
            "toggleSettings" => self.handle_toggle_settings(),
            "saveSettings" => self.handle_save_settings(msg.data),
            "addDbConfig" => self.handle_add_db_config(msg.data),
            "updateDbConfig" => self.handle_update_db_config(msg.data),
            "deleteDbConfig" => self.handle_delete_db_config(msg.data),
            "switchMode" => self.handle_switch_mode(msg.data),
            "completeCode" => self.handle_complete_code(msg.data, sender),
            "openChart" => self.handle_open_chart(msg.data),
            _ => {
                println!("[Bridge] 未知 action: {}", msg.action);
                Ok(false)
            }
        }
    }

    // ===== 图表生成 =====

    /// 发送提示词，提交图表生成任务
    fn handle_send_prompt(
        &mut self,
        data: serde_json::Value,
        sender: &ComponentSender<MainModel>,
    ) -> std::result::Result<bool, Error> {
        if self.is_generating {
            return Ok(false);
        }
        let prompt = data
            .get("prompt")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let files: Vec<String> = data
            .get("files")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        let viz_mode_str = data
            .get("vizMode")
            .and_then(|v| v.as_str())
            .unwrap_or("auto");
        let viz_mode = match viz_mode_str {
            "chart" => api::types::VizMode::Chart,
            "scientific" => api::types::VizMode::Scientific,
            _ => api::types::VizMode::Auto,
        };
        let db_name = data.get("dbConfig").and_then(|v| v.as_str());
        let db_config = db_name
            .and_then(|name| self.settings.db_configs.iter().find(|db| db.name == name))
            .map(|db| db.to_json_string());

        if prompt.trim().is_empty() {
            self.js_add_message("assistant", "请输入分析需求。");
            return Ok(true);
        }
        if files.is_empty() && db_config.is_none() {
            self.js_add_message("assistant", "请先选择数据文件或数据库。");
            return Ok(true);
        }

        self.files = files.clone();
        self.js_start_task_message("正在提交分析任务，首先对数据进行质量检查和清洗，然后基于数据特征生成可视化方案。");
        self.is_generating = true;
        self.js_set_generating(true);
        self.js_set_status("提交中...");

        let client = self.client.clone();
        let sender = sender.clone();
        let model_cfg = self.settings.active_model_config();
        let (model_url, model_type, model_api_key) = match &model_cfg {
            Some(m) => (Some(m.model_url.clone()), Some(m.model_type.clone()), Some(m.model_api_key.clone())),
            None => (None, None, None),
        };
        let mcp_prompt = self.settings.mcp_prompt.clone();
        let skill_prompt = self.settings.skill_prompt.clone();

        std::thread::spawn(move || {
            let handle = tokio_handle();
            handle.block_on(async move {
                let request = api::types::GenerateChartRequest {
                    file_paths: files,
                    user_prompt: prompt,
                    viz_mode,
                    db_config,
                    config: None,
                    model_url,
                    model_type,
                    model_api_key,
                    mcp_prompt,
                    skill_prompt,
                };
                match client.generate_chart(&request).await {
                    Ok(resp) => {
                        let task_id = resp.task_id.clone();
                        sender.post(MainMessage::AppendLog(format!("任务已提交: {}", task_id)));
                        sender.post(MainMessage::SetStatus("生成中...".to_string()));
                        sender.post(MainMessage::TaskStarted(task_id.clone()));

                        let ws_url = client.ws_task_url(&task_id);
                        let api_key = client.api_key().to_string();
                        let ws_task =
                            tokio::task::spawn_blocking(move || {
                                connect_websocket_blocking(&ws_url, &api_key)
                            });
                        let ws_result =
                            tokio::time::timeout(std::time::Duration::from_secs(300), ws_task).await;
                        let mut need_poll = false;
                        match ws_result {
                            Ok(Ok(Ok(notification))) => {
                                if notification.status == "success" {
                                    let (html_files, charts, agent_logs) = match notification.result {
                                        Some(r) => (r.html_file_paths, r.charts, r.agent_logs),
                                        None => (Vec::new(), Vec::new(), Vec::new()),
                                    };
                                    for log in agent_logs {
                                        sender.post(MainMessage::AppendLog(log));
                                    }
                                    sender.post(MainMessage::TaskCompleted { charts, html_files });
                                } else if notification.status == "cancelled" {
                                    sender.post(MainMessage::TaskCancelled);
                                } else {
                                    let err = notification.error.unwrap_or_else(|| "任务失败".to_string());
                                    sender.post(MainMessage::TaskFailed(format!("任务失败: {}", err)));
                                }
                            }
                            Ok(Ok(Err(e))) => {
                                sender.post(MainMessage::AppendLog(format!(
                                    "WebSocket 等待失败，回退到轮询: {}",
                                    e
                                )));
                                need_poll = true;
                            }
                            Ok(Err(_)) => {
                                sender.post(MainMessage::AppendLog(
                                    "WebSocket 任务异常退出，回退到轮询".to_string(),
                                ));
                                need_poll = true;
                            }
                            Err(_) => {
                                sender.post(MainMessage::AppendLog(
                                    "WebSocket 等待超时（5 分钟），回退到轮询".to_string(),
                                ));
                                need_poll = true;
                            }
                        }
                        if need_poll {
                            match client
                                .poll_task_until_done(&task_id, |elapsed| {
                                    let percent = ((elapsed as f64 / 300.0) * 100.0).min(95.0);
                                    sender.post(MainMessage::SetProgress {
                                        percent,
                                        text: format!("生成中... 已等待 {}s", elapsed),
                                    });
                                })
                                .await
                            {
                                Ok(task_resp) => {
                                    use api::types::TaskStatus;
                                    match task_resp.status {
                                        TaskStatus::Success => {
                                            let (html_files, charts, agent_logs) = match task_resp.result {
                                                Some(r) => (r.html_file_paths, r.charts, r.agent_logs),
                                                None => (Vec::new(), Vec::new(), Vec::new()),
                                            };
                                            for log in agent_logs {
                                                sender.post(MainMessage::AppendLog(log));
                                            }
                                            sender.post(MainMessage::TaskCompleted { charts, html_files });
                                        }
                                        TaskStatus::Cancelled => {
                                            sender.post(MainMessage::TaskCancelled);
                                        }
                                        _ => {
                                            let err = task_resp.error.unwrap_or_else(|| "任务失败".to_string());
                                            sender.post(MainMessage::TaskFailed(format!("任务失败: {}", err)));
                                        }
                                    }
                                }
                                Err(e) => {
                                    sender.post(MainMessage::TaskFailed(format!("轮询失败: {}", e)));
                                }
                            }
                        }
                    }
                    Err(e) => {
                        sender.post(MainMessage::TaskFailed(format!("提交失败: {}", e)));
                    }
                }
            });
        });
        Ok(true)
    }

    /// 取消当前生成任务
    fn handle_cancel_task(&mut self, sender: &ComponentSender<MainModel>) -> std::result::Result<bool, Error> {
        if !self.is_generating {
            return Ok(false);
        }
        if let Some(task_id) = &self.task_id {
            let client = self.client.clone();
            let task_id = task_id.clone();
            std::thread::spawn(move || {
                let handle = tokio_handle();
                handle.block_on(async move {
                    let url = format!("{}/api/task/{}/cancel", client.base_url(), task_id);
                    let _ = client.raw_post(&url).await;
                });
            });
        }
        self.is_generating = false;
        self.task_id = None;
        self.js_set_generating(false);
        self.js_cancel_task();
        self.js_set_status("已取消");
        Ok(true)
    }

    // ===== 文件操作 =====

    /// 打开文件夹并扫描数据文件
    pub(crate) async fn handle_open_folder(&mut self) -> std::result::Result<bool, Error> {
        if let Some(p) = FileBox::new()
            .title("选择数据文件夹")
            .open_folder(&self.window)?
            .await?
        {
            let mut found = Vec::new();
            let exts = ["xlsx", "xls", "csv", "json", "pdf", "txt", "py"];
            if let Ok(entries) = std::fs::read_dir(&p) {
                for entry in entries.flatten() {
                    if let Some(ext) = entry.path().extension().and_then(|e| e.to_str()) {
                        if exts.contains(&ext.to_lowercase().as_str()) {
                            if let Some(s) = entry.path().to_str() {
                                found.push(s.to_string());
                            }
                        }
                    }
                }
            }
            found.sort();
            self.project_files = found.clone();
            let proj_name = p
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("项目")
                .to_string();
            self.js(&format!(
                "state.projectName='{}'",
                Self::js_escape(&proj_name)
            ));
            let file_pairs: Vec<(String, String)> = found
                .iter()
                .map(|p| (p.clone(), filename_from_path(p)))
                .collect();
            self.js_set_file_list(&file_pairs);
            self.js_show_toast(
                &format!("已打开文件夹，发现 {} 个数据文件。", file_pairs.len()),
                "success",
            );
        }
        Ok(true)
    }

    /// 打开文件对话框附加文件
    pub(crate) async fn handle_attach_file(&mut self) -> std::result::Result<bool, Error> {
        let file_box = match self.app_mode {
            AppMode::Chat => FileBox::new()
                .title("选择数据文件")
                .add_filter(("Excel 文件", "*.xlsx"))
                .add_filter(("CSV 文件", "*.csv"))
                .add_filter(("所有文件", "*.*")),
            AppMode::CodeCompletion => FileBox::new()
                .title("选择 Python 文件")
                .add_filter(("Python 文件", "*.py"))
                .add_filter(("所有文件", "*.*")),
        };
        if let Some(p) = file_box.open(&self.window)?.await? {
            let path_str = p.to_string_lossy().into_owned();
            self.js_add_file(&path_str);
            self.js_show_toast(
                &format!("已添加文件: {}", filename_from_path(&path_str)),
                "success",
            );
        }
        Ok(true)
    }

    // ===== 聊天 =====

    /// 清空聊天并开始新对话
    fn handle_new_chat(&mut self) -> std::result::Result<bool, Error> {
        self.js_clear_messages();
        Ok(true)
    }

    // ===== 历史记录 =====

    /// 从 API 加载对话列表
    fn handle_load_history(
        &mut self,
        sender: &ComponentSender<MainModel>,
    ) -> std::result::Result<bool, Error> {
        // JS 初始化后首次请求，同步数据库配置到前端（供 DB 选择弹窗使用）
        let configs = self.settings.db_configs.clone();
        self.js_set_db_configs(&configs);
        let client = self.client.clone();
        let sender = sender.clone();
        std::thread::spawn(move || {
            let handle = tokio_handle();
            handle.block_on(async move {
                match client.list_conversations(20, 0).await {
                    Ok(resp) => {
                        sender.post(MainMessage::HistoryLoaded(resp.conversations));
                    }
                    Err(e) => {
                        sender.post(MainMessage::ShowToast { message: format!("加载历史失败: {}", e), toast_type: "error".to_string() });
                    }
                }
            });
        });
        Ok(true)
    }

    /// 用对话列表更新 UI
    pub(crate) fn handle_history_loaded(
        &mut self,
        convs: Vec<api::types::ConversationSummary>,
    ) -> std::result::Result<bool, Error> {
        self.conversations = convs.clone();
        self.js_set_conversation_list(&convs);
        Ok(true)
    }

    /// 获取并显示对话详情
    fn handle_view_detail(
        &mut self,
        data: serde_json::Value,
        sender: &ComponentSender<MainModel>,
    ) -> std::result::Result<bool, Error> {
        let conv_id = match data.get("conversationId").and_then(|v| v.as_str()) {
            Some(id) => id.to_string(),
            None => return Ok(false),
        };
        self.js_set_status(&format!("正在获取对话详情: {}", conv_id));
        let client = self.client.clone();
        let sender = sender.clone();
        std::thread::spawn(move || {
            let handle = tokio_handle();
            handle.block_on(async move {
                match client.get_conversation(&conv_id).await {
                    Ok(detail) => {
                        sender.post(MainMessage::ConversationDetailLoaded(detail));
                    }
                    Err(e) => {
                        sender.post(MainMessage::ShowToast { message: format!("获取详情失败: {}", e), toast_type: "error".to_string() });
                    }
                }
            });
        });
        Ok(true)
    }

    /// 删除选中的对话
    fn handle_delete_conversation(
        &mut self,
        data: serde_json::Value,
        sender: &ComponentSender<MainModel>,
    ) -> std::result::Result<bool, Error> {
        let conv_id = match data.get("conversationId").and_then(|v| v.as_str()) {
            Some(id) => id.to_string(),
            None => return Ok(false),
        };
        let client = self.client.clone();
        let sender = sender.clone();
        std::thread::spawn(move || {
            let handle = tokio_handle();
            handle.block_on(async move {
                match client.delete_conversation(&conv_id).await {
                    Ok(()) => {
                        sender.post(MainMessage::ConversationDeleted);
                    }
                    Err(e) => {
                        sender.post(MainMessage::ShowToast { message: format!("删除失败: {}", e), toast_type: "error".to_string() });
                    }
                }
            });
        });
        Ok(true)
    }

    /// 删除后刷新列表
    pub(crate) fn handle_conversation_deleted(
        &mut self,
        sender: &ComponentSender<MainModel>,
    ) -> std::result::Result<bool, Error> {
        self.js_show_toast("对话已删除", "success");
        self.handle_load_history(sender)
    }

    /// 在聊天中还原对话详情
    pub(crate) fn handle_conversation_detail_loaded(
        &mut self,
        detail: api::types::ConversationDetail,
    ) -> std::result::Result<bool, Error> {
        let charts = detail.charts.clone().unwrap_or_default();
        let html_files = detail.html_file_paths.clone().unwrap_or_default();
        let chart_items: Vec<serde_json::Value> = html_files
            .iter()
            .enumerate()
            .map(|(i, hf)| {
                let ct = charts.get(i).cloned().unwrap_or_else(|| "?".to_string());
                let filename = filename_from_path(hf);
                serde_json::json!({
                    "chartType": ct,
                    "path": self.client.chart_url(&filename),
                    "title": filename,
                    "status": "success",
                })
            })
            .collect();
        let json = serde_json::json!({
            "user_prompt": detail.user_prompt,
            "file_paths": detail.file_paths,
            "viz_mode": detail.viz_mode,
            "status": detail.status,
            "agent_logs": detail.agent_logs,
            "chart_items": chart_items,
            "error": detail.error,
            "created_at": detail.created_at,
        });
        self.js_restore_conversation(&json.to_string());
        Ok(true)
    }

    // ===== 任务事件 =====

    /// 存储 task_id
    pub(crate) fn handle_task_started(&mut self, task_id: String) -> std::result::Result<bool, Error> {
        self.task_id = Some(task_id);
        Ok(false)
    }

    /// 任务完成，在聊天中展示图表卡片
    pub(crate) fn handle_task_completed(
        &mut self,
        charts: Vec<String>,
        html_files: Vec<String>,
    ) -> std::result::Result<bool, Error> {
        // 防竞态:已取消则忽略过期的完成回调
        if !self.is_generating {
            return Ok(false);
        }
        self.is_generating = false;
        self.task_id = None;
        self.js_set_generating(false);

        let total = html_files.len();
        if total == 0 {
            self.js_complete_task(
                &serde_json::json!({ "type": "charts", "items": [] }).to_string(),
            );
        } else {
            let items: Vec<serde_json::Value> = (0..total)
                .map(|i| {
                    let ct = charts.get(i).cloned().unwrap_or_else(|| "?".to_string());
                    let hf = &html_files[i];
                    // 后端返回的 html_file_paths 可能含目录前缀（如 charts/xxx/chart.html），
                    // 但 /api/chart/<chart_id> 路由不匹配含 / 的路径，需提取纯文件名
                    let filename = filename_from_path(hf);
                    serde_json::json!({
                        "chartType": ct,
                        "path": self.client.chart_url(&filename),
                        "title": filename,
                        "status": "success",
                    })
                })
                .collect();
            let chart_json = serde_json::json!({
                "type": "charts",
                "items": items,
            })
            .to_string();
            self.js_complete_task(&chart_json);
        }
        self.js_set_status("完成");
        Ok(true)
    }

    /// 任务失败
    pub(crate) fn handle_task_failed(&mut self, err: String) -> std::result::Result<bool, Error> {
        // 防竞态:已取消(或已完成)则忽略过期的失败回调
        if !self.is_generating {
            return Ok(false);
        }
        self.is_generating = false;
        self.task_id = None;
        self.js_set_generating(false);
        self.js_fail_task(&format!("任务失败: {}", err));
        self.js_set_status("失败");
        Ok(true)
    }

    /// 任务取消(WS 收到 cancelled 状态,或轮询检测到取消)
    pub(crate) fn handle_task_cancelled(&mut self) -> std::result::Result<bool, Error> {
        // 若已被 handle_cancel_task 处理(is_generating=false),忽略过期回调
        if !self.is_generating {
            return Ok(false);
        }
        self.is_generating = false;
        self.task_id = None;
        self.js_set_generating(false);
        self.js_cancel_task();
        self.js_set_status("已取消");
        Ok(true)
    }

    /// 追加日志
    pub(crate) fn handle_append_log(&mut self, msg: String) -> std::result::Result<bool, Error> {
        self.js_append_log(&msg);
        Ok(true)
    }

    /// 更新状态栏
    pub(crate) fn handle_set_status(&mut self, msg: String) -> std::result::Result<bool, Error> {
        self.js_set_status(&msg);
        Ok(true)
    }

    /// 更新进度条
    pub(crate) fn handle_set_progress(
        &mut self,
        percent: f64,
        text: String,
    ) -> std::result::Result<bool, Error> {
        self.js_set_progress(percent, &text);
        Ok(true)
    }

    /// 显示 Toast 通知
    pub(crate) fn handle_show_toast(
        &mut self,
        message: String,
        toast_type: String,
    ) -> std::result::Result<bool, Error> {
        self.js_show_toast(&message, &toast_type);
        Ok(true)
    }

    // ===== 模式切换 =====

    /// 切换模式
    fn handle_switch_mode(&mut self, data: serde_json::Value) -> std::result::Result<bool, Error> {
        let mode = data.get("mode").and_then(|v| v.as_str()).unwrap_or("chat");
        match mode {
            "code" => {
                self.app_mode = AppMode::CodeCompletion;
                self.js_set_mode("code");
            }
            _ => {
                self.app_mode = AppMode::Chat;
                self.js_set_mode("chat");
            }
        }
        Ok(true)
    }

    // ===== 代码补全 =====

    /// 提交代码补全请求
    fn handle_complete_code(
        &mut self,
        data: serde_json::Value,
        sender: &ComponentSender<MainModel>,
    ) -> std::result::Result<bool, Error> {
        if self.is_generating {
            return Ok(false);
        }
        let prompt = data
            .get("prompt")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let files: Vec<String> = data
            .get("files")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();

        if files.is_empty() {
            self.js_add_message("assistant", "请先选择 .py 文件。");
            return Ok(true);
        }
        if prompt.trim().is_empty() {
            self.js_add_message("assistant", "请输入补全需求。");
            return Ok(true);
        }

        self.files = files.clone();
        self.js_start_task_message("正在补全代码...");
        self.is_generating = true;
        self.js_set_generating(true);
        self.js_set_status("补全中...");

        let client = self.client.clone();
        let sender = sender.clone();
        let model_cfg = self.settings.active_model_config();
        let (model_url, model_type, model_api_key) = match &model_cfg {
            Some(m) => (Some(m.model_url.clone()), Some(m.model_type.clone()), Some(m.model_api_key.clone())),
            None => (None, None, None),
        };

        std::thread::spawn(move || {
            let handle = tokio_handle();
            handle.block_on(async move {
                let request = api::types::CompleteVizCodeRequest {
                    code_file_paths: files,
                    user_prompt: prompt,
                    scientific_lib: None,
                    model_url,
                    model_type,
                    model_api_key,
                };
                match client.complete_viz_code(&request).await {
                    Ok(resp) => {
                        match resp.results.into_iter().next() {
                            Some(r) => {
                                let libs_str = if r.recommended_libs.is_empty() {
                                    String::new()
                                } else {
                                    format!("依赖库: {}\n", r.recommended_libs.join(", "))
                                };
                                let snippet = r
                                    .inserted_snippet
                                    .or_else(|| r.completed_code.clone())
                                    .unwrap_or_default();
                                let code_text = format!(
                                    "说明: {}\n{}代码:\n{}",
                                    r.explanation.unwrap_or_default(),
                                    libs_str,
                                    snippet
                                );
                                let result = serde_json::json!({
                                    "type": "code",
                                    "code": code_text,
                                })
                                .to_string();
                                sender.post(MainMessage::CodeCompleted(result));
                            }
                            None => {
                                sender.post(MainMessage::TaskFailed(
                                    "代码补全返回空结果".to_string(),
                                ));
                            }
                        }
                    }
                    Err(e) => {
                        sender.post(MainMessage::TaskFailed(format!("代码补全失败: {}", e)));
                    }
                }
            });
        });
        Ok(true)
    }

    /// 在聊天中显示补全结果
    pub(crate) fn handle_code_completed(&mut self, code: String) -> std::result::Result<bool, Error> {
        self.is_generating = false;
        self.js_set_generating(false);
        self.js_complete_code_task(&code);
        self.js_set_status("完成");
        Ok(true)
    }

    // ===== 设置 =====

    /// 显示/隐藏设置面板
    fn handle_toggle_settings(&mut self) -> std::result::Result<bool, Error> {
        if self.show_settings {
            self.show_settings = false;
            self.js_hide_settings();
        } else {
            self.show_settings = true;
            let s = self.settings.clone();
            self.js_show_settings(&s);
        }
        Ok(true)
    }

    /// 保存设置
    fn handle_save_settings(&mut self, data: serde_json::Value) -> std::result::Result<bool, Error> {
        self.settings.backend_url = data
            .get("backend")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        self.settings.api_key = data
            .get("apiKey")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        self.settings.model_url = opt_string(
            data.get("modelUrl")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        );
        self.settings.model_type = opt_string(
            data.get("modelType")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        );
        self.settings.model_api_key = opt_string(
            data.get("modelKey")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        );

        // 解析模型配置列表（前端卡片式编辑后整体回传）
        if let Some(arr) = data.get("modelConfigs").and_then(|v| v.as_array()) {
            let old_configs = std::mem::take(&mut self.settings.model_configs);
            let mut new_configs: Vec<api::types::ModelConfig> = Vec::new();
            let ts = chrono::Local::now().timestamp_millis();
            for (idx, item) in arr.iter().enumerate() {
                let name = item
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if name.trim().is_empty() {
                    continue;
                }
                let id = item
                    .get("id")
                    .and_then(|v| v.as_str())
                    .and_then(|id| old_configs.iter().find(|m| m.id == id).map(|m| m.id.clone()))
                    .unwrap_or_else(|| format!("model_{}_{}", ts, idx));
                new_configs.push(api::types::ModelConfig {
                    id,
                    name,
                    model_type: item
                        .get("modelType")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    model_url: item
                        .get("modelUrl")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    model_api_key: item
                        .get("modelApiKey")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    enabled: item
                        .get("enabled")
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false),
                });
            }
            self.settings.model_configs = new_configs;
        }

        self.settings.mcp_prompt = opt_string(
            data.get("mcp")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        );
        self.settings.skill_prompt = opt_string(
            data.get("skill")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        );

        // 解析数据库配置列表（前端卡片式编辑后整体回传）
        if let Some(arr) = data.get("dbConfigs").and_then(|v| v.as_array()) {
            let old_configs = std::mem::take(&mut self.settings.db_configs);
            let mut new_configs: Vec<api::types::DbConfig> = Vec::new();
            let ts = chrono::Local::now().timestamp_millis();
            for (idx, item) in arr.iter().enumerate() {
                let name = item
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if name.trim().is_empty() {
                    continue;
                }
                let id = old_configs
                    .iter()
                    .find(|d| d.name == name)
                    .map(|d| d.id.clone())
                    .unwrap_or_else(|| format!("db_{}_{}", ts, idx));
                new_configs.push(api::types::DbConfig {
                    id,
                    name,
                    db_type: item
                        .get("dbType")
                        .and_then(|v| v.as_str())
                        .unwrap_or("MySQL")
                        .to_string(),
                    host: item
                        .get("host")
                        .and_then(|v| v.as_str())
                        .unwrap_or("localhost")
                        .to_string(),
                    port: item
                        .get("port")
                        .and_then(|v| v.as_str())
                        .unwrap_or("3306")
                        .to_string(),
                    user: item
                        .get("user")
                        .and_then(|v| v.as_str())
                        .unwrap_or("root")
                        .to_string(),
                    password: item
                        .get("password")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    database: item
                        .get("database")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }
            self.settings.db_configs = new_configs;
        }

        match self.settings.save() {
            Ok(()) => {
                self.js_show_toast("设置已保存", "success");
                let configs = self.settings.db_configs.clone();
                self.js_set_db_configs(&configs);
            }
            Err(e) => {
                self.js_show_toast(&format!("设置保存失败: {}", e), "error");
            }
        }
        self.backend_url = self.settings.backend_display();
        self.client = api::ApiClient::new(&self.settings.backend_url, &self.settings.api_key);
        self.show_settings = false;
        self.js_hide_settings();
        self.js_set_status("设置已更新");
        let backend_for_js = self.settings.backend_url.clone();
        self.js_set_backend(&backend_for_js);
        Ok(true)
    }

    // ===== 数据库配置 =====

    /// 按名称选择数据库配置（由前端 DB 选择弹窗触发）
    fn handle_select_db(&mut self, data: serde_json::Value) -> std::result::Result<bool, Error> {
        let name = match data.get("name").and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => {
                self.js_show_toast("未选择数据库", "info");
                return Ok(true);
            }
        };
        match self.settings.db_configs.iter().find(|d| d.name == name).cloned() {
            Some(db) => {
                self.selected_db = Some(db);
                self.js_set_selected_db(&name);
                self.js_show_toast(&format!("已选择数据库: {}", name), "success");
            }
            None => {
                self.js_show_toast("未找到该数据库配置", "error");
            }
        }
        Ok(true)
    }

    /// 添加数据库配置
    fn handle_add_db_config(&mut self, data: serde_json::Value) -> std::result::Result<bool, Error> {
        let name = data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if name.trim().is_empty() {
            self.js_show_toast("请输入配置名称", "error");
            return Ok(true);
        }
        let config = api::types::DbConfig {
            id: format!("db_{}", chrono::Local::now().timestamp_millis()),
            name,
            db_type: data
                .get("dbType")
                .and_then(|v| v.as_str())
                .unwrap_or("MySQL")
                .to_string(),
            host: data
                .get("host")
                .and_then(|v| v.as_str())
                .unwrap_or("localhost")
                .to_string(),
            port: data
                .get("port")
                .and_then(|v| v.as_str())
                .unwrap_or("3306")
                .to_string(),
            user: data
                .get("user")
                .and_then(|v| v.as_str())
                .unwrap_or("root")
                .to_string(),
            password: data
                .get("password")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            database: data
                .get("database")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        };
        self.settings.db_configs.push(config);
        let configs = self.settings.db_configs.clone();
        self.js_set_db_configs(&configs);
        self.js_show_toast("数据库配置已添加", "success");
        Ok(true)
    }

    /// 更新数据库配置
    fn handle_update_db_config(
        &mut self,
        data: serde_json::Value,
    ) -> std::result::Result<bool, Error> {
        let index = data.get("index").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
        if index >= self.settings.db_configs.len() {
            self.js_show_toast("无效的配置索引", "error");
            return Ok(true);
        }
        let name = data
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if name.trim().is_empty() {
            self.js_show_toast("请输入配置名称", "error");
            return Ok(true);
        }
        let config = &mut self.settings.db_configs[index];
        config.name = name;
        config.db_type = data
            .get("dbType")
            .and_then(|v| v.as_str())
            .unwrap_or("MySQL")
            .to_string();
        config.host = data
            .get("host")
            .and_then(|v| v.as_str())
            .unwrap_or("localhost")
            .to_string();
        config.port = data
            .get("port")
            .and_then(|v| v.as_str())
            .unwrap_or("3306")
            .to_string();
        config.user = data
            .get("user")
            .and_then(|v| v.as_str())
            .unwrap_or("root")
            .to_string();
        config.password = data
            .get("password")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        config.database = data
            .get("database")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let configs = self.settings.db_configs.clone();
        self.js_set_db_configs(&configs);
        self.js_show_toast("数据库配置已更新", "success");
        Ok(true)
    }

    /// 删除数据库配置
    fn handle_delete_db_config(
        &mut self,
        data: serde_json::Value,
    ) -> std::result::Result<bool, Error> {
        let index = data.get("index").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
        if index < self.settings.db_configs.len() {
            self.settings.db_configs.remove(index);
            let configs = self.settings.db_configs.clone();
            self.js_set_db_configs(&configs);
            self.js_show_toast("数据库配置已删除", "success");
        }
        Ok(true)
    }

    // ===== 图表查看 =====

    /// 打开图表（在浏览器和 WebView 查看器中）
    fn handle_open_chart(&mut self, data: serde_json::Value) -> std::result::Result<bool, Error> {
        if let Some(path) = data.get("path").and_then(|v| v.as_str()) {
            #[cfg(target_os = "windows")]
            {
                std::process::Command::new("cmd")
                    .args(["/C", "start", "", path])
                    .spawn()
                    .ok();
            }
            self.js_open_chart(path);
        }
        Ok(true)
    }
}
