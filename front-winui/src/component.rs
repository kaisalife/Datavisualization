use winio::prelude::*;
use crate::api;
use crate::bridge::{BridgeMessage, BridgeServer};
use crate::messages::MainMessage;
use crate::state::{AppMode, AppSettings};
use crate::{Error, MainModel};

impl Component for MainModel {
    type Error = Error;
    type Event = ();
    type Init<'a> = ();
    type Message = MainMessage;

    async fn init(_init: Self::Init<'_>, sender: &ComponentSender<Self>) -> std::result::Result<Self, Error> {
        let settings = AppSettings::load();
        let backend_display = settings.backend_display();

        // 创建桥接通道
        let (tx, rx) = tokio::sync::mpsc::unbounded_channel::<BridgeMessage>();

        // 在 tokio 运行时中启动桥接 HTTP 服务器
        let port = crate::runtime::tokio_handle()
            .block_on(async { BridgeServer::start(tx).await })
            .expect("桥接服务器启动失败")
            .port;

        init! {
            window: Window = (()) => { text: "DataVisual - 多源数据可视化平台", size: Size::new(1200.0, 800.0) },
            webview: WebView = (&window),
        }

        // 加载 HTML 并注入拆分的 CSS/JS，替换端口占位符
        let css = include_str!("app.css");
        let js = [
            include_str!("js/state.js"),
            include_str!("js/utils.js"),
            include_str!("js/messages.js"),
            include_str!("js/charts.js"),
            include_str!("js/sidebar.js"),
            include_str!("js/settings.js"),
            include_str!("js/input.js"),
            include_str!("js/api.js"),
        ].concat();
        let html = include_str!("app.html")
            .replace("__CSS__", css)
            .replace("__JS__", &js)
            .replace("__BRIDGE_PORT__", &port.to_string());
        webview.set_html(&html)?;

        // 显示窗口
        window.set_visible(true)?;
        let _ = window.set_backdrop(Backdrop::Mica);

        let client = api::ApiClient::new(&settings.backend_url, &settings.api_key);

        let mut model = Self {
            window,
            webview,
            app_mode: AppMode::Chat,
            files: Vec::new(),
            project_files: Vec::new(),
            is_generating: false,
            backend_url: backend_display,
            client,
            task_id: None,
            conversations: Vec::new(),
            selected_db: None,
            settings,
            show_settings: false,
            bridge_rx: Some(rx),
        };

        // 注入后端地址到 JS（供 Trace WebSocket 直连，避免硬编码）
        let backend_for_js = model.settings.backend_url.clone();
        model.js_set_backend(&backend_for_js);

        // HTML 加载后会自动通过桥接发送 loadHistory 请求
        let _ = sender;
        Ok(model)
    }

    async fn start(&mut self, sender: &ComponentSender<Self>) -> ! {
        // 在 tokio 运行时中转发桥接消息到主组件
        if let Some(rx) = self.bridge_rx.take() {
            let sender = sender.clone();
            crate::runtime::tokio_handle().spawn(async move {
                let mut rx = rx;
                while let Some(msg) = rx.recv().await {
                    sender.post(MainMessage::BridgeAction(msg));
                }
            });
        }

        start! {
            sender, default: MainMessage::Noop,
            self.window => { WindowEvent::Close => MainMessage::Close, WindowEvent::Resize => MainMessage::WindowResized },
            self.webview => { WebViewEvent::Navigated => MainMessage::Noop },
        }
    }

    async fn update_children(&mut self) -> std::result::Result<bool, Error> {
        let a: std::result::Result<bool, Error> = update_children!(self.window);
        let b: std::result::Result<bool, Error> = update_children!(self.webview);
        Ok(a? || b?)
    }

    async fn update(&mut self, message: Self::Message, sender: &ComponentSender<Self>) -> std::result::Result<bool, Error> {
        match message {
            MainMessage::Noop => Ok(false),
            MainMessage::Close => {
                sender.output(());
                Ok(false)
            }
            MainMessage::WindowResized => Ok(true),
            MainMessage::BridgeAction(msg) => self.handle_bridge_action(msg, sender).await,
            MainMessage::TaskStarted(task_id) => self.handle_task_started(task_id),
            MainMessage::TaskCompleted { charts, html_files } => self.handle_task_completed(charts, html_files),
            MainMessage::TaskFailed(err) => self.handle_task_failed(err),
            MainMessage::TaskCancelled => self.handle_task_cancelled(),
            MainMessage::AppendLog(msg) => self.handle_append_log(msg),
            MainMessage::SetStatus(msg) => self.handle_set_status(msg),
            MainMessage::SetProgress { percent, text } => self.handle_set_progress(percent, text),
            MainMessage::ShowToast { message, toast_type } => self.handle_show_toast(message, toast_type),
            MainMessage::OpenChartsDir(dir) => self.handle_open_charts_dir_exec(dir),
            MainMessage::HistoryLoaded(convs) => self.handle_history_loaded(convs),
            MainMessage::ConversationDetailLoaded(detail) => self.handle_conversation_detail_loaded(detail),
            MainMessage::ConversationDeleted => self.handle_conversation_deleted(sender),
            MainMessage::CodeCompleted(code) => self.handle_code_completed(code),
        }
    }

    fn render(&mut self, _sender: &ComponentSender<Self>) -> std::result::Result<(), Error> {
        let csize = self.window.client_size()?;
        self.webview.set_loc(Point::new(0.0, 0.0))?;
        self.webview.set_size(Size::new(csize.width, csize.height))?;
        Ok(())
    }

    fn render_children(&mut self) -> std::result::Result<(), Error> {
        self.window.render()?;
        self.webview.render()?;
        Ok(())
    }
}
