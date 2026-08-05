use crate::api;
use crate::state::AppSettings;
use crate::MainModel;

impl MainModel {
    /// 转义字符串以便安全地嵌入 JavaScript 单引号字符串
    pub(crate) fn js_escape(s: &str) -> String {
        s.replace('\\', "\\\\")
            .replace('\'', "\\'")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
            .replace('\t', "\\t")
    }

    /// 执行 JavaScript 代码（fire-and-forget）
    pub(crate) fn js(&mut self, code: &str) {
        let _ = self.webview.run_javascript(code);
    }

    /// 添加聊天消息
    pub(crate) fn js_add_message(&mut self, role: &str, content: &str) {
        self.js(&format!(
            "window.app.addMessage('{}','{}')",
            Self::js_escape(role),
            Self::js_escape(content)
        ));
    }

    /// 清空聊天消息
    pub(crate) fn js_clear_messages(&mut self) {
        self.js("window.app.clearMessages()");
    }

    /// 追加 Agent 日志
    pub(crate) fn js_append_log(&mut self, text: &str) {
        self.js(&format!(
            "window.app.appendLog('{}')",
            Self::js_escape(text)
        ));
    }

    /// 设置进度条
    pub(crate) fn js_set_progress(&mut self, percent: f64, text: &str) {
        self.js(&format!(
            "window.app.setProgress({},'{}')",
            percent,
            Self::js_escape(text)
        ));
    }

    /// 设置生成状态
    pub(crate) fn js_set_generating(&mut self, generating: bool) {
        self.js(&format!("window.app.setGenerating({})", generating));
    }

    /// 清空输入框
    pub(crate) fn js_clear_input(&mut self) {
        self.js("window.app.clearInput()");
    }

    /// 设置对话列表
    pub(crate) fn js_set_conversation_list(&mut self, convs: &[api::types::ConversationSummary]) {
        let json_arr: Vec<serde_json::Value> = convs
            .iter()
            .map(|c| {
                serde_json::json!({
                    "id": c.conversation_id,
                    "prompt": c.user_prompt,
                    "createdAt": c.created_at,
                    "status": c.status,
                })
            })
            .collect();
        let json = serde_json::to_string(&json_arr).unwrap_or_else(|_| "[]".to_string());
        self.js(&format!(
            "window.app.setConversationList('{}')",
            Self::js_escape(&json)
        ));
    }

    /// 设置文件列表（侧边栏文件浏览）
    pub(crate) fn js_set_file_list(&mut self, files: &[(String, String)]) {
        let json_arr: Vec<serde_json::Value> = files
            .iter()
            .map(|(path, name)| {
                serde_json::json!({ "path": path, "name": name })
            })
            .collect();
        let json = serde_json::to_string(&json_arr).unwrap_or_else(|_| "[]".to_string());
        self.js(&format!(
            "window.app.setFileList('{}')",
            Self::js_escape(&json)
        ));
    }

    /// 设置已选文件标签
    pub(crate) fn js_set_file_chips(&mut self, files: &[String]) {
        let json = serde_json::to_string(files).unwrap_or_else(|_| "[]".to_string());
        self.js(&format!(
            "window.app.setFileChips('{}')",
            Self::js_escape(&json)
        ));
    }

    /// 添加单个文件到已选列表（不覆盖已有文件）
    pub(crate) fn js_add_file(&mut self, path: &str) {
        self.js(&format!(
            "if(state.files.indexOf('{}')<0){{state.files.push('{}');renderFileChips();}}",
            Self::js_escape(path),
            Self::js_escape(path)
        ));
    }

    /// 设置模式（chat / code）
    pub(crate) fn js_set_mode(&mut self, mode: &str) {
        self.js(&format!(
            "window.app.setMode('{}')",
            Self::js_escape(mode)
        ));
    }

    /// 显示设置面板
    pub(crate) fn js_show_settings(&mut self, settings: &AppSettings) {
        let json = serde_json::json!({
            "backend": settings.backend_url,
            "apiKey": settings.api_key,
            "modelUrl": settings.model_url,
            "modelType": settings.model_type,
            "modelKey": settings.model_api_key,
            "modelConfigs": settings.model_configs.iter().map(|m| {
                serde_json::json!({
                    "id": m.id,
                    "name": m.name,
                    "modelType": m.model_type,
                    "modelUrl": m.model_url,
                    "modelApiKey": m.model_api_key,
                    "enabled": m.enabled,
                })
            }).collect::<Vec<_>>(),
            "mcp": settings.mcp_prompt,
            "skill": settings.skill_prompt,
            "dbConfigs": settings.db_configs.iter().map(|db| {
                serde_json::json!({
                    "name": db.name,
                    "dbType": db.db_type,
                    "host": db.host,
                    "port": db.port,
                    "user": db.user,
                    "password": db.password,
                    "database": db.database,
                })
            }).collect::<Vec<_>>(),
        })
        .to_string();
        self.js(&format!(
            "window.app.showSettings('{}')",
            Self::js_escape(&json)
        ));
    }

    /// 隐藏设置面板
    pub(crate) fn js_hide_settings(&mut self) {
        self.js("window.app.hideSettings()");
    }

    /// 显示 Toast 通知
    pub(crate) fn js_show_toast(&mut self, message: &str, toast_type: &str) {
        self.js(&format!(
            "window.app.showToast('{}','{}')",
            Self::js_escape(message),
            Self::js_escape(toast_type)
        ));
    }

    /// 设置状态栏文本
    pub(crate) fn js_set_status(&mut self, text: &str) {
        self.js(&format!(
            "window.app.setStatus('{}')",
            Self::js_escape(text)
        ));
    }

    /// 设置数据库配置列表
    pub(crate) fn js_set_db_configs(&mut self, configs: &[api::types::DbConfig]) {
        let json_arr: Vec<serde_json::Value> = configs
            .iter()
            .map(|db| {
                serde_json::json!({
                    "name": db.name,
                    "dbType": db.db_type,
                    "host": db.host,
                    "port": db.port,
                    "user": db.user,
                    "password": db.password,
                    "database": db.database,
                })
            })
            .collect();
        let json = serde_json::to_string(&json_arr).unwrap_or_else(|_| "[]".to_string());
        self.js(&format!(
            "window.app.setDbConfigs('{}')",
            Self::js_escape(&json)
        ));
    }

    /// 设置选中的数据库名称
    pub(crate) fn js_set_selected_db(&mut self, name: &str) {
        self.js(&format!(
            "window.app.setSelectedDb('{}')",
            Self::js_escape(name)
        ));
    }

    /// 在 WebView 中打开图表查看器
    pub(crate) fn js_open_chart(&mut self, url: &str) {
        self.js(&format!(
            "window.app.openChart('{}')",
            Self::js_escape(url)
        ));
    }

    /// 启动一个活动任务消息（含进度条、日志区、图表区）
    pub(crate) fn js_start_task_message(&mut self, text: &str) {
        self.js(&format!(
            "window.app.startTaskMessage('{}')",
            Self::js_escape(text)
        ));
    }

    /// 任务完成，填充图表卡片到活动消息
    pub(crate) fn js_complete_task(&mut self, charts_json: &str) {
        self.js(&format!(
            "window.app.completeTask('{}')",
            Self::js_escape(charts_json)
        ));
    }

    /// 任务失败，在活动消息中显示错误
    pub(crate) fn js_fail_task(&mut self, err: &str) {
        self.js(&format!(
            "window.app.failTask('{}')",
            Self::js_escape(err)
        ));
    }

    /// 还原历史对话（从后端数据库加载后重建聊天界面）
    pub(crate) fn js_restore_conversation(&mut self, detail_json: &str) {
        self.js(&format!(
            "window.app.restoreConversation('{}')",
            Self::js_escape(detail_json)
        ));
    }

    /// 代码补全完成，在活动任务消息中展示代码
    pub(crate) fn js_complete_code_task(&mut self, code_json: &str) {
        self.js(&format!(
            "window.app.completeCodeTask('{}')",
            Self::js_escape(code_json)
        ));
    }

    /// 取消任务，更新活动任务消息状态
    pub(crate) fn js_cancel_task(&mut self) {
        self.js("window.app.cancelTask()");
    }

    /// 注入后端地址到 JS（供 Trace WebSocket 等直连使用，避免硬编码 127.0.0.1:5000）
    pub(crate) fn js_set_backend(&mut self, url: &str) {
        self.js(&format!(
            "window.app.setBackend('{}')",
            Self::js_escape(url)
        ));
    }
}
