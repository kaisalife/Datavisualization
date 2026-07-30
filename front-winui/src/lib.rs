mod api;

use std::sync::OnceLock;
use serde::{Deserialize, Serialize};
use tokio::runtime::Runtime;
use winio::prelude::*;

/// 全局 tokio 运行时（用 OnceLock 保证只初始化一次）
///
/// winio 使用 compio 运行时，无法直接 .await tokio future。
/// 在单独线程中通过 handle.block_on 执行 API 调用，用 sender.post 回传结果。
static TOKIO_RT: OnceLock<Runtime> = OnceLock::new();

/// 获取全局 tokio 运行时的 Handle
fn tokio_handle() -> tokio::runtime::Handle {
    TOKIO_RT
        .get_or_init(|| Runtime::new().expect("无法创建 tokio 运行时"))
        .handle()
        .clone()
}

#[derive(Debug)]
pub struct Error(pub anyhow::Error);
impl From<anyhow::Error> for Error {
    fn from(e: anyhow::Error) -> Self {
        Self(e)
    }
}
impl From<winio::Error> for Error {
    fn from(e: winio::Error) -> Self {
        Self(anyhow::anyhow!("{}", e))
    }
}

/// ListBox 显示模式：文件列表或历史对话列表
#[derive(Debug, PartialEq)]
enum ListboxMode {
    Files,
    History,
}

/// 应用设置（可序列化到 settings.json）
///
/// 用户可通过设置面板配置后端地址、API Key、模型参数等，
/// 替代环境变量。设置文件保存在 exe 同级目录下。
#[derive(Clone, Serialize, Deserialize)]
struct AppSettings {
    backend_url: String,
    api_key: String,
    model_url: Option<String>,
    model_type: Option<String>,
    model_api_key: Option<String>,
    mcp_prompt: Option<String>,
    skill_prompt: Option<String>,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            backend_url: std::env::var("BACKEND_URL")
                .unwrap_or_else(|_| "http://localhost:5000".to_string()),
            api_key: std::env::var("API_KEY").unwrap_or_default(),
            model_url: std::env::var("MODEL_URL").ok(),
            model_type: std::env::var("MODEL_TYPE").ok(),
            model_api_key: std::env::var("MODEL_API_KEY").ok(),
            mcp_prompt: std::env::var("MCP_PROMPT").ok(),
            skill_prompt: std::env::var("SKILL_PROMPT").ok(),
        }
    }
}

impl AppSettings {
    /// 设置文件路径（exe 同级目录下的 settings.json）
    fn file_path() -> Option<std::path::PathBuf> {
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.join("settings.json")))
    }

    /// 从文件加载设置，失败时返回默认值
    fn load() -> Self {
        if let Some(path) = Self::file_path() {
            if let Ok(content) = std::fs::read_to_string(&path) {
                if let Ok(settings) = serde_json::from_str::<AppSettings>(&content) {
                    return settings;
                }
            }
        }
        Self::default()
    }

    /// 保存设置到文件
    fn save(&self) -> std::result::Result<(), String> {
        let path = Self::file_path().ok_or_else(|| "无法获取 exe 路径".to_string())?;
        let json = serde_json::to_string_pretty(self).map_err(|e| e.to_string())?;
        std::fs::write(&path, json).map_err(|e| e.to_string())
    }

    /// 返回用于状态栏显示的后端地址（去掉协议前缀）
    fn backend_display(&self) -> String {
        self.backend_url
            .strip_prefix("http://")
            .or_else(|| self.backend_url.strip_prefix("https://"))
            .unwrap_or(&self.backend_url)
            .to_string()
    }
}

pub struct MainModel {
    window: Child<Window>,
    btn_select_file: Child<Button>,
    btn_generate: Child<Button>,
    btn_cancel: Child<Button>,
    btn_load_history: Child<Button>,
    btn_clear: Child<Button>,
    btn_view_detail: Child<Button>,
    btn_delete_conv: Child<Button>,
    btn_resubmit: Child<Button>,
    edit_prompt: Child<Edit>,
    label_status: Child<Label>,
    label_statusbar: Child<Label>,
    label_sidebar_title: Child<Label>,
    listbox_files: Child<ListBox>,
    textbox_log: Child<TextBox>,
    // db_config 与 viz_mode 输入
    textbox_db_config: Child<TextBox>,
    combo_viz_mode: Child<ComboBox>,
    label_db_config: Child<Label>,
    label_viz_mode: Child<Label>,
    // 代码补全
    btn_complete_code: Child<Button>,
    edit_code: Child<Edit>,
    label_code: Child<Label>,
    // 设置面板控件
    btn_settings: Child<Button>,
    label_set_title: Child<Label>,
    label_set_backend: Child<Label>,
    edit_set_backend: Child<Edit>,
    label_set_apikey: Child<Label>,
    edit_set_apikey: Child<Edit>,
    label_set_model_url: Child<Label>,
    edit_set_model_url: Child<Edit>,
    label_set_model_type: Child<Label>,
    edit_set_model_type: Child<Edit>,
    label_set_model_key: Child<Label>,
    edit_set_model_key: Child<Edit>,
    label_set_mcp: Child<Label>,
    textbox_set_mcp: Child<TextBox>,
    label_set_skill: Child<Label>,
    textbox_set_skill: Child<TextBox>,
    btn_save_settings: Child<Button>,
    btn_cancel_settings: Child<Button>,
    // 应用状态
    files: Vec<String>,
    is_generating: bool,
    log_text: String,
    // 状态栏最近状态文本与后端地址（用于刷新底部状态栏）
    last_status: String,
    backend_url: String,
    // API 客户端与当前任务
    client: api::ApiClient,
    task_id: Option<String>,
    // 历史对话
    conversations: Vec<api::types::ConversationSummary>,
    listbox_mode: ListboxMode,
    // 应用设置
    settings: AppSettings,
    show_settings: bool,
}

#[derive(Debug)]
pub enum MainMessage {
    Noop,
    Close,
    SelectFile,
    GenerateChart,
    CancelTask,
    LoadHistory,
    ClearFiles,
    PromptChanged,
    AppendLog(String),
    SetStatus(String),
    TaskStarted(String),
    TaskCompleted(Vec<String>),
    TaskFailed(String),
    HistoryLoaded(Vec<api::types::ConversationSummary>),
    ViewDetail,
    DeleteConversation,
    ResubmitPrompt,
    ConversationDetailLoaded(String),
    ConversationDeleted,
    VizModeChanged,
    // 代码补全
    CompleteCode,
    CodeCompleted(String),
    // 窗口大小变化
    WindowResized,
    // 设置面板
    ToggleSettings,
    SaveSettings,
    CancelSettings,
}

/// 格式化对话详情为可读字符串
fn format_conversation_detail(detail: &api::types::ConversationDetail) -> String {
    let mut lines = Vec::new();
    lines.push("=== 对话详情 ===".to_string());
    lines.push(format!("ID: {}", detail.conversation_id));
    lines.push(format!(
        "状态: {}",
        detail.status.as_deref().unwrap_or("?")
    ));
    lines.push(format!("创建时间: {}", detail.created_at));
    lines.push(format!(
        "可视化模式: {}",
        detail.viz_mode.as_deref().unwrap_or("?")
    ));
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

/// 阻塞式连接 WebSocket 并等待任务完成通知
///
/// 使用 tungstenite 同步连接后端 `/ws/task/<task_id>`，读取一条 JSON 消息
/// 并解析为 `TaskCompleteNotification`。由于 tungstenite 是同步 API，
/// 调用方应通过 `tokio::task::spawn_blocking` 在独立线程执行，避免阻塞 tokio 运行时。
///
/// 参数：
/// - `ws_url`: WebSocket 端点 URL（由 `ApiClient::ws_task_url` 构造）
/// - `api_key`: 鉴权用的 API Key（写入 `X-API-Key` 请求头）
///
/// 返回：解析后的 `TaskCompleteNotification`，或错误描述字符串。
fn connect_websocket_blocking(
    ws_url: &str,
    api_key: &str,
) -> std::result::Result<api::types::TaskCompleteNotification, String> {
    use tungstenite::handshake::client::generate_key;

    let request = tungstenite::http::Request::builder()
        .uri(ws_url)
        .header("X-API-Key", api_key)
        .header("Connection", "Upgrade")
        .header("Upgrade", "websocket")
        .header("Sec-WebSocket-Version", "13")
        .header("Sec-WebSocket-Key", generate_key())
        .body(())
        .map_err(|e| format!("构建 WebSocket 请求失败: {}", e))?;

    let (mut socket, _response) =
        tungstenite::connect(request).map_err(|e| format!("WebSocket 连接失败: {}", e))?;

    loop {
        match socket.read() {
            Ok(tungstenite::Message::Text(text)) => {
                let notification: api::types::TaskCompleteNotification =
                    serde_json::from_str(&text)
                        .map_err(|e| format!("解析 WebSocket 消息失败: {}", e))?;
                return Ok(notification);
            }
            Ok(tungstenite::Message::Close(_)) => {
                return Err("WebSocket 连接已关闭".to_string());
            }
            Ok(_) => continue,
            Err(e) => {
                return Err(format!("WebSocket 读取错误: {}", e));
            }
        }
    }
}

impl Component for MainModel {
    type Error = Error;
    type Event = ();
    type Init<'a> = ();
    type Message = MainMessage;

    async fn init(
        _init: Self::Init<'_>,
        _sender: &ComponentSender<Self>,
    ) -> std::result::Result<Self, Error> {
        // TODO: 强制深色主题。winio 未公开 set_preferred_app_mode / PreferredAppMode，
        // 其 runtime 已调用 set_preferred_app_mode(AllowDark) 跟随系统主题。
        // 若需强制深色，可启用 winio 的 "win32-dark-mode" feature，并通过
        // winio-ui-windows-common 调用 set_preferred_app_mode(PreferredAppMode::ForceDark)。
        // 从 settings.json 加载设置，失败时回退到环境变量
        let settings = AppSettings::load();
        let backend_display = settings.backend_display();
        init! {
            window: Window = (()) => {
                text: "DataVisual - 多源数据可视化平台",
                size: Size::new(1000.0, 750.0),
            },
            btn_select_file: Button = (&window) => {
                text: "📂 文件",
            },
            btn_generate: Button = (&window) => {
                text: "▶ 生成",
            },
            btn_cancel: Button = (&window) => {
                text: "✕ 取消",
            },
            btn_load_history: Button = (&window) => {
                text: "📜 历史",
            },
            btn_clear: Button = (&window) => {
                text: "🗑 清空",
            },
            btn_view_detail: Button = (&window) => {
                text: "📋 详情",
            },
            btn_delete_conv: Button = (&window) => {
                text: "✕ 删除",
            },
            btn_resubmit: Button = (&window) => {
                text: "↻ 重提",
            },
            edit_prompt: Edit = (&window) => {
                text: "",
            },
            label_status: Label = (&window) => {
                text: "就绪",
            },
            label_statusbar: Label = (&window) => {
                text: " 就绪 | 文件: 0 | 任务: 空闲 | 后端: localhost:5000 ",
            },
            label_sidebar_title: Label = (&window) => {
                text: "文件列表",
            },
            listbox_files: ListBox = (&window),
            textbox_log: TextBox = (&window) => {
                text: "",
                readonly: true,
            },
            label_db_config: Label = (&window) => {
                text: "数据库配置 (JSON, 可选):",
            },
            textbox_db_config: TextBox = (&window) => {
                text: "",
            },
            label_viz_mode: Label = (&window) => {
                text: "可视化模式 (auto/chart/scientific):",
            },
            combo_viz_mode: ComboBox = (&window),
            label_code: Label = (&window) => {
                text: "代码补全 (输入需求，使用已选文件):",
            },
            edit_code: Edit = (&window) => {
                text: "",
            },
            btn_complete_code: Button = (&window) => {
                text: "补全",
            },
            btn_settings: Button = (&window) => {
                text: "⚙ 设置",
            },
            label_set_title: Label = (&window) => {
                text: "设置",
            },
            label_set_backend: Label = (&window) => {
                text: "后端地址:",
            },
            edit_set_backend: Edit = (&window) => {
                text: "",
            },
            label_set_apikey: Label = (&window) => {
                text: "API Key:",
            },
            edit_set_apikey: Edit = (&window) => {
                text: "",
            },
            label_set_model_url: Label = (&window) => {
                text: "Model URL:",
            },
            edit_set_model_url: Edit = (&window) => {
                text: "",
            },
            label_set_model_type: Label = (&window) => {
                text: "Model Type:",
            },
            edit_set_model_type: Edit = (&window) => {
                text: "",
            },
            label_set_model_key: Label = (&window) => {
                text: "Model API Key:",
            },
            edit_set_model_key: Edit = (&window) => {
                text: "",
            },
            label_set_mcp: Label = (&window) => {
                text: "MCP Prompt:",
            },
            textbox_set_mcp: TextBox = (&window) => {
                text: "",
            },
            label_set_skill: Label = (&window) => {
                text: "Skill Prompt:",
            },
            textbox_set_skill: TextBox = (&window) => {
                text: "",
            },
            btn_save_settings: Button = (&window) => {
                text: "💾 保存",
            },
            btn_cancel_settings: Button = (&window) => {
                text: "返回",
            },
        }
        window.show()?;
        // Mica 背景效果（Windows 11 22H2+ 支持，失败时静默忽略不影响主流程）
        let _ = window.set_backdrop(Backdrop::Mica);
        // 为所有按钮设置 ToolTip 提示（仅在 init 中设置一次）
        btn_select_file.set_tooltip("选择数据文件（Excel/CSV/PDF/JSON）")?;
        btn_generate.set_tooltip("提交图表生成任务")?;
        btn_cancel.set_tooltip("取消当前任务")?;
        btn_load_history.set_tooltip("加载历史对话列表")?;
        btn_clear.set_tooltip("清空文件列表")?;
        btn_view_detail.set_tooltip("查看选中对话的详情")?;
        btn_delete_conv.set_tooltip("删除选中的对话")?;
        btn_resubmit.set_tooltip("用历史提示词重新生成")?;
        btn_settings.set_tooltip("配置后端地址、API Key、模型参数")?;
        btn_complete_code.set_tooltip("调用 AI 补全可视化代码")?;
        btn_save_settings.set_tooltip("保存设置并重新连接")?;
        btn_cancel_settings.set_tooltip("放弃修改并返回")?;
        // 添加 viz_mode 选项并默认选中 auto
        combo_viz_mode.push("auto")?;
        combo_viz_mode.push("chart")?;
        combo_viz_mode.push("scientific")?;
        combo_viz_mode.set_selection(0)?;
        // 创建 API 客户端（使用 settings 中的配置）
        let client = api::ApiClient::new(&settings.backend_url, &settings.api_key);
        let mut model = Self {
            window,
            btn_select_file,
            btn_generate,
            btn_cancel,
            btn_load_history,
            btn_clear,
            btn_view_detail,
            btn_delete_conv,
            btn_resubmit,
            edit_prompt,
            label_status,
            label_statusbar,
            label_sidebar_title,
            listbox_files,
            textbox_log,
            textbox_db_config,
            combo_viz_mode,
            label_db_config,
            label_viz_mode,
            btn_complete_code,
            edit_code,
            label_code,
            btn_settings,
            label_set_title,
            label_set_backend,
            edit_set_backend,
            label_set_apikey,
            edit_set_apikey,
            label_set_model_url,
            edit_set_model_url,
            label_set_model_type,
            edit_set_model_type,
            label_set_model_key,
            edit_set_model_key,
            label_set_mcp,
            textbox_set_mcp,
            label_set_skill,
            textbox_set_skill,
            btn_save_settings,
            btn_cancel_settings,
            files: Vec::new(),
            is_generating: false,
            log_text: String::new(),
            last_status: "就绪".to_string(),
            backend_url: backend_display,
            client,
            task_id: None,
            conversations: Vec::new(),
            listbox_mode: ListboxMode::Files,
            settings,
            show_settings: false,
        };
        model.refresh_statusbar()?;
        Ok(model)
    }

    async fn start(&mut self, sender: &ComponentSender<Self>) -> ! {
        start! {
            sender, default: MainMessage::Noop,
            self.window => {
                WindowEvent::Close => MainMessage::Close,
                WindowEvent::Resize => MainMessage::WindowResized,
            },
            self.btn_select_file => {
                ButtonEvent::Click => MainMessage::SelectFile,
            },
            self.btn_generate => {
                ButtonEvent::Click => MainMessage::GenerateChart,
            },
            self.btn_cancel => {
                ButtonEvent::Click => MainMessage::CancelTask,
            },
            self.btn_load_history => {
                ButtonEvent::Click => MainMessage::LoadHistory,
            },
            self.btn_clear => {
                ButtonEvent::Click => MainMessage::ClearFiles,
            },
            self.btn_view_detail => {
                ButtonEvent::Click => MainMessage::ViewDetail,
            },
            self.btn_delete_conv => {
                ButtonEvent::Click => MainMessage::DeleteConversation,
            },
            self.btn_resubmit => {
                ButtonEvent::Click => MainMessage::ResubmitPrompt,
            },
            self.edit_prompt => {
                EditEvent::Change => MainMessage::PromptChanged,
            },
            self.listbox_files => {
                ListBoxEvent::Select => MainMessage::Noop,
            },
            self.combo_viz_mode => {
                ComboBoxEvent::Select => MainMessage::VizModeChanged,
            },
            self.btn_complete_code => {
                ButtonEvent::Click => MainMessage::CompleteCode,
            },
            self.btn_settings => {
                ButtonEvent::Click => MainMessage::ToggleSettings,
            },
            self.btn_save_settings => {
                ButtonEvent::Click => MainMessage::SaveSettings,
            },
            self.btn_cancel_settings => {
                ButtonEvent::Click => MainMessage::CancelSettings,
            },
        }
    }

    async fn update_children(&mut self) -> std::result::Result<bool, Error> {
        // 控件数量超过宏的元组上限（32），分两批更新
        let a: std::result::Result<bool, Error> = update_children!(
            self.window,
            self.btn_select_file,
            self.btn_generate,
            self.btn_cancel,
            self.btn_load_history,
            self.btn_clear,
            self.btn_view_detail,
            self.btn_delete_conv,
            self.btn_resubmit,
            self.edit_prompt,
            self.label_status,
            self.label_statusbar,
            self.label_sidebar_title,
            self.listbox_files,
            self.textbox_log,
            self.label_db_config,
            self.textbox_db_config,
            self.label_viz_mode,
            self.combo_viz_mode,
            self.label_code,
            self.edit_code,
            self.btn_complete_code
        );
        let b: std::result::Result<bool, Error> = update_children!(
            self.btn_settings,
            self.label_set_title,
            self.label_set_backend,
            self.edit_set_backend,
            self.label_set_apikey,
            self.edit_set_apikey,
            self.label_set_model_url,
            self.edit_set_model_url,
            self.label_set_model_type,
            self.edit_set_model_type,
            self.label_set_model_key,
            self.edit_set_model_key,
            self.label_set_mcp,
            self.textbox_set_mcp,
            self.label_set_skill,
            self.textbox_set_skill,
            self.btn_save_settings,
            self.btn_cancel_settings
        );
        Ok(a? || b?)
    }

    async fn update(
        &mut self,
        message: Self::Message,
        sender: &ComponentSender<Self>,
    ) -> std::result::Result<bool, Error> {
        match message {
            MainMessage::Noop => Ok(false),
            MainMessage::Close => {
                sender.output(());
                Ok(false)
            }
            MainMessage::SelectFile => {
                if let Some(p) = FileBox::new()
                    .title("选择数据文件")
                    .add_filter(("Excel 文件", "*.xlsx"))
                    .add_filter(("CSV 文件", "*.csv"))
                    .add_filter(("所有文件", "*.*"))
                    .open(&self.window)
                    .await?
                {
                    let path_str = p.to_string_lossy().into_owned();
                    let filename = p
                        .file_name()
                        .and_then(|n| n.to_str())
                        .unwrap_or("file")
                        .to_string();
                    // 若当前为历史模式，切换回文件模式并重建列表
                    if self.listbox_mode == ListboxMode::History {
                        self.listbox_mode = ListboxMode::Files;
                        self.listbox_files.clear()?;
                        for f in &self.files {
                            let fname = std::path::Path::new(f)
                                .file_name()
                                .and_then(|n| n.to_str())
                                .unwrap_or("file")
                                .to_string();
                            self.listbox_files.push(fname)?;
                        }
                    }
                    self.files.push(path_str);
                    self.listbox_files.push(filename)?;
                    sender.post(MainMessage::AppendLog(format!("已添加文件: {:?}", p)));
                    sender.post(MainMessage::SetStatus(format!(
                        "已选 {} 个文件",
                        self.files.len()
                    )));
                }
                Ok(true)
            }
            MainMessage::GenerateChart => {
                if self.is_generating {
                    return Ok(false);
                }
                if self.files.is_empty() {
                    sender.post(MainMessage::SetStatus("请先选择文件".to_string()));
                    return Ok(true);
                }
                let prompt = self.edit_prompt.text()?;
                if prompt.trim().is_empty() {
                    sender.post(MainMessage::SetStatus("请输入提示词".to_string()));
                    return Ok(true);
                }

                // 读取 db_config（可选）
                let db_config = {
                    let text = self.textbox_db_config.text()?;
                    if text.trim().is_empty() {
                        None
                    } else {
                        Some(text)
                    }
                };
                // 读取 viz_mode
                let viz_mode = match self.combo_viz_mode.selection()? {
                    Some(1) => api::types::VizMode::Chart,
                    Some(2) => api::types::VizMode::Scientific,
                    _ => api::types::VizMode::Auto,
                };

                self.is_generating = true;
                sender.post(MainMessage::AppendLog(format!("提示词: {}", prompt)));
                sender
                    .post(MainMessage::AppendLog(format!("文件数: {}", self.files.len())));
                sender.post(MainMessage::AppendLog(format!(
                    "可视化模式: {}",
                    viz_mode.as_str()
                )));
                if db_config.is_some() {
                    sender
                        .post(MainMessage::AppendLog("已附带数据库配置".to_string()));
                }
                sender.post(MainMessage::SetStatus("提交中...".to_string()));

                // 在单独线程中执行 tokio API 调用，通过 sender.post 回传结果
                let client = self.client.clone();
                let files = self.files.clone();
                let prompt = prompt.clone();
                let sender = sender.clone();
                // 从 settings 克隆模型参数，替代环境变量
                let model_url = self.settings.model_url.clone();
                let model_type = self.settings.model_type.clone();
                let model_api_key = self.settings.model_api_key.clone();
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
                                sender.post(MainMessage::AppendLog(format!(
                                    "任务已提交: {}",
                                    task_id
                                )));
                                sender.post(MainMessage::SetStatus("生成中...".to_string()));
                                sender.post(MainMessage::TaskStarted(task_id.clone()));

                                // 先尝试 WebSocket 等待任务完成通知（推送），失败/超时则回退到轮询
                                let ws_url = client.ws_task_url(&task_id);
                                let api_key = client.api_key().to_string();
                                let ws_task = tokio::task::spawn_blocking(move || {
                                    connect_websocket_blocking(&ws_url, &api_key)
                                });
                                let ws_result = tokio::time::timeout(
                                    std::time::Duration::from_secs(300),
                                    ws_task,
                                )
                                .await;

                                let mut need_poll = false;
                                // ws_result 有三层 Result：
                                //   外层 timeout -> Result<_, Elapsed>
                                //   中层 JoinHandle -> Result<_, JoinError>
                                //   内层 connect_websocket_blocking -> Result<Notification, String>
                                match ws_result {
                                    Ok(Ok(Ok(notification))) => {
                                        if notification.status == "success" {
                                            let (html_files, agent_logs) =
                                                match notification.result {
                                                    Some(r) => (r.html_file_paths, r.agent_logs),
                                                    None => (Vec::new(), Vec::new()),
                                                };
                                            sender.post(MainMessage::TaskCompleted(html_files));
                                            for log in agent_logs {
                                                sender.post(MainMessage::AppendLog(log));
                                            }
                                        } else {
                                            let err = notification
                                                .error
                                                .unwrap_or_else(|| "任务失败".to_string());
                                            sender.post(MainMessage::TaskFailed(format!(
                                                "任务失败: {}",
                                                err
                                            )));
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
                                    // 轮询任务状态（回调签名 Fn(u64)，仅传 elapsed）
                                    match client
                                        .poll_task_until_done(&task_id, |elapsed| {
                                            sender.post(MainMessage::SetStatus(format!(
                                                "生成中... 已等待 {}s",
                                                elapsed
                                            )));
                                        })
                                        .await
                                    {
                                        Ok(task_resp) => {
                                            let html_files: Vec<String> = task_resp
                                                .result
                                                .map(|r| r.html_file_paths)
                                                .unwrap_or_default();
                                            sender.post(MainMessage::TaskCompleted(html_files));
                                        }
                                        Err(e) => {
                                            sender.post(MainMessage::TaskFailed(format!(
                                                "轮询失败: {}",
                                                e
                                            )));
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
            MainMessage::CancelTask => {
                if !self.is_generating {
                    return Ok(false);
                }
                // 发送取消请求到后端（端点：POST /api/task/<task_id>/cancel）
                if let Some(task_id) = &self.task_id {
                    let client = self.client.clone();
                    let task_id = task_id.clone();
                    std::thread::spawn(move || {
                        let handle = tokio_handle();
                        handle.block_on(async move {
                            let cancel_url = format!(
                                "{}/api/task/{}/cancel",
                                client.base_url(),
                                task_id
                            );
                            let _ = client.raw_post(&cancel_url).await;
                        });
                    });
                }
                self.is_generating = false;
                self.task_id = None;
                sender.post(MainMessage::AppendLog("任务已取消".to_string()));
                sender.post(MainMessage::SetStatus("已取消".to_string()));
                Ok(true)
            }
            MainMessage::LoadHistory => {
                sender.post(MainMessage::AppendLog("正在加载历史对话...".to_string()));
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
                                sender.post(MainMessage::AppendLog(format!(
                                    "加载历史失败: {}",
                                    e
                                )));
                            }
                        }
                    });
                });
                Ok(true)
            }
            MainMessage::ClearFiles => {
                self.files.clear();
                self.conversations.clear();
                self.listbox_files.clear()?;
                self.listbox_mode = ListboxMode::Files;
                sender.post(MainMessage::AppendLog("已清空列表".to_string()));
                sender.post(MainMessage::SetStatus("就绪".to_string()));
                Ok(true)
            }
            MainMessage::PromptChanged => Ok(false),
            MainMessage::TaskStarted(task_id) => {
                self.task_id = Some(task_id);
                Ok(false)
            }
            MainMessage::AppendLog(msg) => {
                let ts = chrono::Local::now().format("%H:%M:%S").to_string();
                self.log_text.push_str(&format!("[{}] {}\n", ts, msg));
                self.textbox_log.set_text(&self.log_text)?;
                Ok(true)
            }
            MainMessage::SetStatus(msg) => {
                self.last_status = msg;
                self.label_status.set_text(&self.last_status)?;
                self.refresh_statusbar()?;
                Ok(true)
            }
            MainMessage::TaskCompleted(html_files) => {
                self.is_generating = false;
                self.task_id = None;
                sender.post(MainMessage::AppendLog(format!(
                    "任务完成，生成 {} 个图表",
                    html_files.len()
                )));
                // 用默认浏览器打开每个图表
                for (i, file) in html_files.iter().enumerate() {
                    let url = self.client.chart_url(file);
                    sender.post(MainMessage::AppendLog(format!(
                        "打开图表 {}/{}: {}",
                        i + 1,
                        html_files.len(),
                        file
                    )));
                    #[cfg(target_os = "windows")]
                    {
                        std::process::Command::new("cmd")
                            .args(["/C", "start", "", &url])
                            .spawn()
                            .ok();
                    }
                }
                sender.post(MainMessage::SetStatus("完成".to_string()));
                Ok(true)
            }
            MainMessage::TaskFailed(err) => {
                self.is_generating = false;
                self.task_id = None;
                sender.post(MainMessage::AppendLog(format!("任务失败: {}", err)));
                sender.post(MainMessage::SetStatus("失败".to_string()));
                Ok(true)
            }
            MainMessage::HistoryLoaded(convs) => {
                if convs.is_empty() {
                    sender.post(MainMessage::AppendLog("无历史对话".to_string()));
                    sender.post(MainMessage::SetStatus("无历史对话".to_string()));
                } else {
                    let count = convs.len();
                    self.conversations = convs.clone();
                    self.listbox_mode = ListboxMode::History;
                    self.listbox_files.clear()?;
                    for c in &convs {
                        let status = c.status.as_deref().unwrap_or("?");
                        let prompt_preview: String = c.user_prompt.chars().take(20).collect();
                        let ellipsis =
                            if c.user_prompt.chars().count() > 20 { "..." } else { "" };
                        let summary = format!(
                            "[{}] {} | {}{}",
                            status, c.created_at, prompt_preview, ellipsis
                        );
                        self.listbox_files.push(summary)?;
                    }
                    sender.post(MainMessage::AppendLog(format!(
                        "已加载 {} 个历史对话",
                        count
                    )));
                    sender.post(MainMessage::SetStatus(format!(
                        "已加载 {} 个历史对话",
                        count
                    )));
                }
                Ok(true)
            }
            MainMessage::ViewDetail => {
                if self.listbox_mode != ListboxMode::History {
                    sender.post(MainMessage::SetStatus("请先加载历史对话".to_string()));
                    return Ok(true);
                }
                let selected = self.get_listbox_selected_index()?;
                match selected {
                    Some(idx) if idx < self.conversations.len() => {
                        let conv_id = self.conversations[idx].conversation_id.clone();
                        sender.post(MainMessage::AppendLog(format!(
                            "正在获取对话详情: {}",
                            conv_id
                        )));
                        let client = self.client.clone();
                        let sender = sender.clone();
                        std::thread::spawn(move || {
                            let handle = tokio_handle();
                            handle.block_on(async move {
                                match client.get_conversation(&conv_id).await {
                                    Ok(detail) => {
                                        let formatted = format_conversation_detail(&detail);
                                        sender
                                            .post(MainMessage::ConversationDetailLoaded(formatted));
                                    }
                                    Err(e) => {
                                        sender.post(MainMessage::AppendLog(format!(
                                            "获取详情失败: {}",
                                            e
                                        )));
                                    }
                                }
                            });
                        });
                    }
                    _ => {
                        sender
                            .post(MainMessage::SetStatus("请先选择一个对话".to_string()));
                    }
                }
                Ok(true)
            }
            MainMessage::DeleteConversation => {
                if self.listbox_mode != ListboxMode::History {
                    sender.post(MainMessage::SetStatus("请先加载历史对话".to_string()));
                    return Ok(true);
                }
                let selected = self.get_listbox_selected_index()?;
                match selected {
                    Some(idx) if idx < self.conversations.len() => {
                        let conv_id = self.conversations[idx].conversation_id.clone();
                        sender.post(MainMessage::AppendLog(format!(
                            "正在删除对话: {}",
                            conv_id
                        )));
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
                                        sender.post(MainMessage::AppendLog(format!(
                                            "删除失败: {}",
                                            e
                                        )));
                                    }
                                }
                            });
                        });
                    }
                    _ => {
                        sender
                            .post(MainMessage::SetStatus("请先选择一个对话".to_string()));
                    }
                }
                Ok(true)
            }
            MainMessage::ResubmitPrompt => {
                if self.listbox_mode != ListboxMode::History {
                    sender.post(MainMessage::SetStatus("请先加载历史对话".to_string()));
                    return Ok(true);
                }
                let selected = self.get_listbox_selected_index()?;
                match selected {
                    Some(idx) if idx < self.conversations.len() => {
                        let prompt = self.conversations[idx].user_prompt.clone();
                        self.edit_prompt.set_text(&prompt)?;
                        sender.post(MainMessage::AppendLog(format!(
                            "已加载历史提示词: {}",
                            prompt
                        )));
                        sender.post(MainMessage::SetStatus(
                            "已加载提示词，可修改后点击生成图表".to_string(),
                        ));
                    }
                    _ => {
                        sender
                            .post(MainMessage::SetStatus("请先选择一个对话".to_string()));
                    }
                }
                Ok(true)
            }
            MainMessage::ConversationDetailLoaded(detail_text) => {
                sender.post(MainMessage::AppendLog(detail_text));
                Ok(true)
            }
            MainMessage::ConversationDeleted => {
                sender.post(MainMessage::AppendLog("对话已删除".to_string()));
                sender.post(MainMessage::SetStatus("已删除，正在刷新列表".to_string()));
                // 刷新历史列表
                sender.post(MainMessage::LoadHistory);
                Ok(true)
            }
            MainMessage::VizModeChanged => {
                let mode = match self.combo_viz_mode.selection()? {
                    Some(1) => "chart",
                    Some(2) => "scientific",
                    _ => "auto",
                };
                sender.post(MainMessage::SetStatus(format!("可视化模式: {}", mode)));
                Ok(false)
            }
            MainMessage::CompleteCode => {
                let code = self.edit_code.text()?;
                if code.trim().is_empty() {
                    sender.post(MainMessage::SetStatus("请输入代码补全需求".to_string()));
                    return Ok(true);
                }
                if self.files.is_empty() {
                    sender.post(MainMessage::SetStatus(
                        "请先选择文件作为代码补全输入".to_string(),
                    ));
                    return Ok(true);
                }
                // 输入框文本作为 user_prompt，已选文件作为 code_file_paths
                let request = api::types::CompleteVizCodeRequest {
                    code_file_paths: self.files.clone(),
                    user_prompt: code,
                    scientific_lib: std::env::var("SCIENTIFIC_LIB").ok(),
                    model_url: self.settings.model_url.clone(),
                    model_type: self.settings.model_type.clone(),
                    model_api_key: self.settings.model_api_key.clone(),
                };
                let client = self.client.clone();
                let sender = sender.clone();
                sender.post(MainMessage::SetStatus("代码补全中...".to_string()));
                std::thread::spawn(move || {
                    let handle = tokio_handle();
                    handle.block_on(async move {
                        match client.complete_viz_code(&request).await {
                            Ok(resp) => {
                                let mut lines = Vec::new();
                                lines.push("=== 代码补全结果 ===".to_string());
                                if !resp.libs.is_empty() {
                                    lines.push(format!("依赖库: {}", resp.libs.join(", ")));
                                }
                                lines.push("说明:".to_string());
                                lines.push(resp.explanation);
                                lines.push("代码:".to_string());
                                lines.push(resp.snippet);
                                sender.post(MainMessage::CodeCompleted(lines.join("\n")));
                            }
                            Err(e) => {
                                sender.post(MainMessage::AppendLog(format!(
                                    "代码补全失败: {}",
                                    e
                                )));
                                sender
                                    .post(MainMessage::SetStatus("代码补全失败".to_string()));
                            }
                        }
                    });
                });
                Ok(true)
            }
            MainMessage::CodeCompleted(result) => {
                sender.post(MainMessage::AppendLog(result));
                sender.post(MainMessage::SetStatus("代码补全完成".to_string()));
                Ok(true)
            }
            MainMessage::WindowResized => {
                // 窗口尺寸变化，触发 render 重新计算布局
                Ok(true)
            }
            MainMessage::ToggleSettings => {
                self.show_settings = !self.show_settings;
                if self.show_settings {
                    // 加载当前设置到编辑框
                    self.edit_set_backend.set_text(&self.settings.backend_url)?;
                    self.edit_set_apikey.set_text(&self.settings.api_key)?;
                    self.edit_set_model_url
                        .set_text(self.settings.model_url.as_deref().unwrap_or(""))?;
                    self.edit_set_model_type
                        .set_text(self.settings.model_type.as_deref().unwrap_or(""))?;
                    self.edit_set_model_key
                        .set_text(self.settings.model_api_key.as_deref().unwrap_or(""))?;
                    self.textbox_set_mcp
                        .set_text(self.settings.mcp_prompt.as_deref().unwrap_or(""))?;
                    self.textbox_set_skill
                        .set_text(self.settings.skill_prompt.as_deref().unwrap_or(""))?;
                    sender.post(MainMessage::SetStatus("设置面板已打开".to_string()));
                } else {
                    sender.post(MainMessage::SetStatus("就绪".to_string()));
                }
                Ok(true)
            }
            MainMessage::SaveSettings => {
                // 从编辑框读取值
                self.settings.backend_url = self.edit_set_backend.text()?;
                self.settings.api_key = self.edit_set_apikey.text()?;
                self.settings.model_url = {
                    let s = self.edit_set_model_url.text()?;
                    if s.trim().is_empty() { None } else { Some(s) }
                };
                self.settings.model_type = {
                    let s = self.edit_set_model_type.text()?;
                    if s.trim().is_empty() { None } else { Some(s) }
                };
                self.settings.model_api_key = {
                    let s = self.edit_set_model_key.text()?;
                    if s.trim().is_empty() { None } else { Some(s) }
                };
                self.settings.mcp_prompt = {
                    let s = self.textbox_set_mcp.text()?;
                    if s.trim().is_empty() { None } else { Some(s) }
                };
                self.settings.skill_prompt = {
                    let s = self.textbox_set_skill.text()?;
                    if s.trim().is_empty() { None } else { Some(s) }
                };

                // 保存到文件
                match self.settings.save() {
                    Ok(()) => {
                        sender.post(MainMessage::AppendLog("设置已保存".to_string()));
                    }
                    Err(e) => {
                        sender.post(MainMessage::AppendLog(format!("设置保存失败: {}", e)));
                    }
                }

                // 更新后端地址显示
                self.backend_url = self.settings.backend_display();

                // 重建 ApiClient
                self.client =
                    api::ApiClient::new(&self.settings.backend_url, &self.settings.api_key);

                // 关闭设置面板
                self.show_settings = false;
                sender.post(MainMessage::SetStatus("设置已更新".to_string()));
                Ok(true)
            }
            MainMessage::CancelSettings => {
                self.show_settings = false;
                sender.post(MainMessage::SetStatus("已取消设置".to_string()));
                Ok(true)
            }
        }
    }

    fn render(&mut self, _sender: &ComponentSender<Self>) -> std::result::Result<(), Error> {
        // 动态布局：基于实际客户区尺寸计算各区域，不对窗口尺寸做钳制；
        // 侧边栏/底部面板在窗口过窄过矮时自动隐藏，控件尺寸仅做最小保护防消失。
        let csize = self.window.client_size()?;
        let total_w = csize.width;
        let total_h = csize.height;
        let gap = 5.0;

        // 1. 工具栏：高度固定，按钮宽度按窗口宽度等分（最小 65px 保证文字可见）
        // 按功能分组重排：文件 | 清空 | 生成 | 取消 | 历史 | 详情 | 删除 | 重提 | 设置
        let toolbar_h = 44.0;
        let btn_count = 9.0_f64;
        let btn_w = ((total_w - gap * (btn_count + 1.0)) / btn_count).max(65.0);
        let btn_h = (toolbar_h - gap * 2.0).max(20.0);
        let btn_y = gap;
        let btn_x = |i: usize| gap + (btn_w + gap) * (i as f64);
        self.btn_select_file.set_loc(Point::new(btn_x(0), btn_y))?;
        self.btn_select_file.set_size(Size::new(btn_w, btn_h))?;
        self.btn_clear.set_loc(Point::new(btn_x(1), btn_y))?;
        self.btn_clear.set_size(Size::new(btn_w, btn_h))?;
        self.btn_generate.set_loc(Point::new(btn_x(2), btn_y))?;
        self.btn_generate.set_size(Size::new(btn_w, btn_h))?;
        self.btn_cancel.set_loc(Point::new(btn_x(3), btn_y))?;
        self.btn_cancel.set_size(Size::new(btn_w, btn_h))?;
        self.btn_load_history.set_loc(Point::new(btn_x(4), btn_y))?;
        self.btn_load_history.set_size(Size::new(btn_w, btn_h))?;
        self.btn_view_detail.set_loc(Point::new(btn_x(5), btn_y))?;
        self.btn_view_detail.set_size(Size::new(btn_w, btn_h))?;
        self.btn_delete_conv.set_loc(Point::new(btn_x(6), btn_y))?;
        self.btn_delete_conv.set_size(Size::new(btn_w, btn_h))?;
        self.btn_resubmit.set_loc(Point::new(btn_x(7), btn_y))?;
        self.btn_resubmit.set_size(Size::new(btn_w, btn_h))?;
        self.btn_settings.set_loc(Point::new(btn_x(8), btn_y))?;
        self.btn_settings.set_size(Size::new(btn_w, btn_h))?;

        // 2. 侧边栏宽度：随窗口宽度动态变化，过窄时隐藏
        let sidebar_w = if total_w < 400.0 {
            0.0 // 窗口太窄，隐藏侧边栏
        } else if total_w < 700.0 {
            (total_w * 0.35).min(200.0) // 窄窗口，按比例缩小
        } else {
            (total_w * 0.25).min(350.0).max(200.0) // 正常窗口，25% 宽度，钳制 200-350
        };

        // 3. 底部面板高度：随窗口高度动态变化，过矮时隐藏
        let bottom_panel_h = if total_h < 400.0 {
            0.0 // 窗口太矮，隐藏底部面板
        } else if total_h < 600.0 {
            80.0 // 矮窗口，缩小底部面板
        } else {
            (total_h * 0.2).min(180.0).max(100.0) // 正常窗口，20% 高度，钳制 100-180
        };

        // 4. 状态栏：固定高度
        let statusbar_h = 28.0;

        // 5. 计算各区域位置和尺寸
        let content_y = toolbar_h + gap;
        let content_h =
            (total_h - toolbar_h - statusbar_h - bottom_panel_h - gap * 3.0).max(50.0);
        let main_x = if sidebar_w > 0.0 { sidebar_w + gap } else { gap };
        let main_w = if sidebar_w > 0.0 {
            total_w - sidebar_w - gap * 2.0
        } else {
            total_w - gap * 2.0
        };
        let main_w = main_w.max(100.0);

        // 状态栏（底部，全宽）
        let statusbar_y = total_h - statusbar_h;
        self.label_statusbar.set_loc(Point::new(0.0, statusbar_y))?;
        self.label_statusbar.set_size(Size::new(total_w.max(20.0), statusbar_h))?;

        // 侧边栏（左侧：文件列表/历史列表），过窄时隐藏
        if sidebar_w > 0.0 {
            let sidebar_title_h = 22.0;
            let sidebar_inner_w = (sidebar_w - gap * 2.0).max(20.0);
            // 侧边栏标题（根据当前模式切换文本）
            let title = if self.listbox_mode == ListboxMode::History {
                "历史对话"
            } else {
                "文件列表"
            };
            self.label_sidebar_title.set_visible(true)?;
            self.label_sidebar_title.set_text(title)?;
            self.label_sidebar_title
                .set_loc(Point::new(gap, content_y))?;
            self.label_sidebar_title
                .set_size(Size::new(sidebar_inner_w, sidebar_title_h))?;

            let listbox_y = content_y + sidebar_title_h + gap;
            let listbox_h = (content_h - sidebar_title_h - gap).max(20.0);
            self.listbox_files.set_visible(true)?;
            self.listbox_files.set_loc(Point::new(gap, listbox_y))?;
            self.listbox_files.set_size(Size::new(sidebar_inner_w, listbox_h))?;
        } else {
            self.label_sidebar_title.set_visible(false)?;
            self.listbox_files.set_visible(false)?;
        }

        if self.show_settings {
            // ===== 设置面板模式：隐藏正常控件，显示设置控件 =====
            self.edit_prompt.set_visible(false)?;
            self.label_status.set_visible(false)?;
            self.textbox_log.set_visible(false)?;
            self.label_db_config.set_visible(false)?;
            self.textbox_db_config.set_visible(false)?;
            self.label_viz_mode.set_visible(false)?;
            self.combo_viz_mode.set_visible(false)?;
            self.label_code.set_visible(false)?;
            self.edit_code.set_visible(false)?;
            self.btn_complete_code.set_visible(false)?;

            // 显示设置控件
            self.label_set_title.set_visible(true)?;
            self.label_set_backend.set_visible(true)?;
            self.edit_set_backend.set_visible(true)?;
            self.label_set_apikey.set_visible(true)?;
            self.edit_set_apikey.set_visible(true)?;
            self.label_set_model_url.set_visible(true)?;
            self.edit_set_model_url.set_visible(true)?;
            self.label_set_model_type.set_visible(true)?;
            self.edit_set_model_type.set_visible(true)?;
            self.label_set_model_key.set_visible(true)?;
            self.edit_set_model_key.set_visible(true)?;
            self.label_set_mcp.set_visible(true)?;
            self.textbox_set_mcp.set_visible(true)?;
            self.label_set_skill.set_visible(true)?;
            self.textbox_set_skill.set_visible(true)?;
            self.btn_save_settings.set_visible(true)?;
            self.btn_cancel_settings.set_visible(true)?;

            // 设置面板布局：占用主区域 + 底部面板空间（底部控件已隐藏）
            let set_x = main_x;
            let set_w = main_w;
            let mut y = content_y + 5.0;

            self.label_set_title.set_loc(Point::new(set_x, y))?;
            self.label_set_title.set_size(Size::new(set_w, 25.0))?;
            y += 35.0;

            let label_w = 120.0;
            let edit_x = set_x + label_w + gap;
            let edit_w = (set_w - label_w - gap).max(100.0);
            let row_h = 28.0;

            // 后端地址
            self.label_set_backend.set_loc(Point::new(set_x, y))?;
            self.label_set_backend.set_size(Size::new(label_w, 25.0))?;
            self.edit_set_backend.set_loc(Point::new(edit_x, y))?;
            self.edit_set_backend.set_size(Size::new(edit_w, 25.0))?;
            y += row_h;

            // API Key
            self.label_set_apikey.set_loc(Point::new(set_x, y))?;
            self.label_set_apikey.set_size(Size::new(label_w, 25.0))?;
            self.edit_set_apikey.set_loc(Point::new(edit_x, y))?;
            self.edit_set_apikey.set_size(Size::new(edit_w, 25.0))?;
            y += row_h;

            // Model URL
            self.label_set_model_url.set_loc(Point::new(set_x, y))?;
            self.label_set_model_url.set_size(Size::new(label_w, 25.0))?;
            self.edit_set_model_url.set_loc(Point::new(edit_x, y))?;
            self.edit_set_model_url.set_size(Size::new(edit_w, 25.0))?;
            y += row_h;

            // Model Type
            self.label_set_model_type.set_loc(Point::new(set_x, y))?;
            self.label_set_model_type.set_size(Size::new(label_w, 25.0))?;
            self.edit_set_model_type.set_loc(Point::new(edit_x, y))?;
            self.edit_set_model_type.set_size(Size::new(edit_w, 25.0))?;
            y += row_h;

            // Model API Key
            self.label_set_model_key.set_loc(Point::new(set_x, y))?;
            self.label_set_model_key.set_size(Size::new(label_w, 25.0))?;
            self.edit_set_model_key.set_loc(Point::new(edit_x, y))?;
            self.edit_set_model_key.set_size(Size::new(edit_w, 25.0))?;
            y += row_h;

            // MCP Prompt（标签 + 多行输入）
            self.label_set_mcp.set_loc(Point::new(set_x, y))?;
            self.label_set_mcp.set_size(Size::new(set_w, 20.0))?;
            y += 25.0;
            self.textbox_set_mcp.set_loc(Point::new(set_x, y))?;
            self.textbox_set_mcp.set_size(Size::new(set_w, 70.0))?;
            y += 75.0;

            // Skill Prompt（标签 + 多行输入）
            self.label_set_skill.set_loc(Point::new(set_x, y))?;
            self.label_set_skill.set_size(Size::new(set_w, 20.0))?;
            y += 25.0;
            self.textbox_set_skill.set_loc(Point::new(set_x, y))?;
            self.textbox_set_skill.set_size(Size::new(set_w, 70.0))?;
            y += 75.0;

            // 保存 / 取消按钮
            let btn_save_w = 100.0;
            let btn_cancel_w = 80.0;
            self.btn_save_settings.set_loc(Point::new(set_x, y))?;
            self.btn_save_settings.set_size(Size::new(btn_save_w, 30.0))?;
            self.btn_cancel_settings
                .set_loc(Point::new(set_x + btn_save_w + gap, y))?;
            self.btn_cancel_settings.set_size(Size::new(btn_cancel_w, 30.0))?;
        } else {
            // ===== 正常模式：显示正常控件，隐藏设置控件 =====
            self.label_set_title.set_visible(false)?;
            self.label_set_backend.set_visible(false)?;
            self.edit_set_backend.set_visible(false)?;
            self.label_set_apikey.set_visible(false)?;
            self.edit_set_apikey.set_visible(false)?;
            self.label_set_model_url.set_visible(false)?;
            self.edit_set_model_url.set_visible(false)?;
            self.label_set_model_type.set_visible(false)?;
            self.edit_set_model_type.set_visible(false)?;
            self.label_set_model_key.set_visible(false)?;
            self.edit_set_model_key.set_visible(false)?;
            self.label_set_mcp.set_visible(false)?;
            self.textbox_set_mcp.set_visible(false)?;
            self.label_set_skill.set_visible(false)?;
            self.textbox_set_skill.set_visible(false)?;
            self.btn_save_settings.set_visible(false)?;
            self.btn_cancel_settings.set_visible(false)?;

            // 主区域内控件：提示词 + 状态 + 日志
            self.edit_prompt.set_visible(true)?;
            self.label_status.set_visible(true)?;
            self.textbox_log.set_visible(true)?;
            let prompt_h = 30.0;
            self.edit_prompt.set_loc(Point::new(main_x, content_y))?;
            self.edit_prompt.set_size(Size::new(main_w, prompt_h))?;

            let status_y = content_y + prompt_h + gap;
            let status_h = 22.0;
            self.label_status.set_loc(Point::new(main_x, status_y))?;
            self.label_status.set_size(Size::new(main_w, status_h))?;

            let log_y = status_y + status_h + gap;
            let log_h = (content_h - prompt_h - status_h - gap * 2.0).max(30.0);
            self.textbox_log.set_loc(Point::new(main_x, log_y))?;
            self.textbox_log.set_size(Size::new(main_w, log_h))?;

            // 底部面板位置
            let bottom_y = content_y + content_h + gap;
            if bottom_panel_h > 0.0 {
                // 左侧：数据库配置（占主区域 35% 宽度）
                self.label_db_config.set_visible(true)?;
                self.textbox_db_config.set_visible(true)?;
                let db_w = (main_w * 0.35).max(100.0);
                self.label_db_config.set_loc(Point::new(main_x, bottom_y))?;
                self.label_db_config.set_size(Size::new(db_w, 20.0))?;
                self.textbox_db_config
                    .set_loc(Point::new(main_x, bottom_y + 22.0))?;
                self.textbox_db_config
                    .set_size(Size::new(db_w, (bottom_panel_h - 22.0).max(30.0)))?;

                // 右侧：可视化模式 + 代码补全（占主区域 65% 宽度）
                self.label_viz_mode.set_visible(true)?;
                self.combo_viz_mode.set_visible(true)?;
                self.label_code.set_visible(true)?;
                self.edit_code.set_visible(true)?;
                self.btn_complete_code.set_visible(true)?;
                let right_x = main_x + db_w + gap;
                let right_w = (main_w - db_w - gap).max(100.0);

                // viz_mode 下拉框
                self.label_viz_mode.set_loc(Point::new(right_x, bottom_y))?;
                self.label_viz_mode.set_size(Size::new(right_w * 0.3, 20.0))?;
                self.combo_viz_mode
                    .set_loc(Point::new(right_x, bottom_y + 22.0))?;
                self.combo_viz_mode
                    .set_size(Size::new((right_w * 0.3).max(80.0), 25.0))?;

                // 代码补全
                let code_x = right_x + right_w * 0.3 + gap;
                let code_w = (right_w * 0.7 - gap).max(80.0);
                let code_row_y = bottom_y + 22.0;
                self.label_code.set_loc(Point::new(code_x, bottom_y))?;
                self.label_code.set_size(Size::new(code_w, 20.0))?;
                let code_edit_w = (code_w * 0.8).max(60.0);
                let code_btn_w = (code_w * 0.2 - gap).max(40.0);
                self.edit_code.set_loc(Point::new(code_x, code_row_y))?;
                self.edit_code.set_size(Size::new(code_edit_w, 25.0))?;
                self.btn_complete_code
                    .set_loc(Point::new(code_x + code_edit_w + gap, code_row_y))?;
                self.btn_complete_code.set_size(Size::new(code_btn_w, 25.0))?;
            } else {
                // 窗口太矮，隐藏底部面板控件
                self.label_db_config.set_visible(false)?;
                self.textbox_db_config.set_visible(false)?;
                self.label_viz_mode.set_visible(false)?;
                self.combo_viz_mode.set_visible(false)?;
                self.label_code.set_visible(false)?;
                self.edit_code.set_visible(false)?;
                self.btn_complete_code.set_visible(false)?;
            }
        }

        // 按钮启用状态
        self.btn_generate
            .set_enabled(!self.is_generating && !self.files.is_empty())?;
        self.btn_cancel.set_enabled(self.is_generating)?;
        // 历史对话操作按钮仅在 History 模式下可用
        let history_mode = self.listbox_mode == ListboxMode::History;
        self.btn_view_detail.set_enabled(history_mode)?;
        self.btn_delete_conv.set_enabled(history_mode)?;
        self.btn_resubmit.set_enabled(history_mode)?;
        Ok(())
    }

    fn render_children(&mut self) -> std::result::Result<(), Error> {
        self.window.render()?;
        self.btn_select_file.render()?;
        self.btn_generate.render()?;
        self.btn_cancel.render()?;
        self.btn_load_history.render()?;
        self.btn_clear.render()?;
        self.btn_view_detail.render()?;
        self.btn_delete_conv.render()?;
        self.btn_resubmit.render()?;
        self.edit_prompt.render()?;
        self.label_status.render()?;
        self.label_statusbar.render()?;
        self.label_sidebar_title.render()?;
        self.listbox_files.render()?;
        self.textbox_log.render()?;
        self.label_db_config.render()?;
        self.textbox_db_config.render()?;
        self.label_viz_mode.render()?;
        self.combo_viz_mode.render()?;
        self.label_code.render()?;
        self.edit_code.render()?;
        self.btn_complete_code.render()?;
        self.btn_settings.render()?;
        self.label_set_title.render()?;
        self.label_set_backend.render()?;
        self.edit_set_backend.render()?;
        self.label_set_apikey.render()?;
        self.edit_set_apikey.render()?;
        self.label_set_model_url.render()?;
        self.edit_set_model_url.render()?;
        self.label_set_model_type.render()?;
        self.edit_set_model_type.render()?;
        self.label_set_model_key.render()?;
        self.edit_set_model_key.render()?;
        self.label_set_mcp.render()?;
        self.textbox_set_mcp.render()?;
        self.label_set_skill.render()?;
        self.textbox_set_skill.render()?;
        self.btn_save_settings.render()?;
        self.btn_cancel_settings.render()?;
        Ok(())
    }
}

impl MainModel {
    /// 获取 ListBox 当前选中项的索引
    fn get_listbox_selected_index(&self) -> std::result::Result<Option<usize>, Error> {
        let len = self.listbox_files.len()?;
        for i in 0..len {
            if self.listbox_files.is_selected(i)? {
                return Ok(Some(i));
            }
        }
        Ok(None)
    }

    /// 刷新底部状态栏文本，汇总当前状态/文件数/任务/后端地址
    fn refresh_statusbar(&mut self) -> std::result::Result<(), Error> {
        let task = if self.is_generating { "生成中" } else { "空闲" };
        let text = format!(
            " {} | 文件: {} | 任务: {} | 后端: {} ",
            self.last_status,
            self.files.len(),
            task,
            self.backend_url
        );
        self.label_statusbar.set_text(text)?;
        Ok(())
    }
}
