use winio::prelude::*;
use crate::api;
use crate::state::{AppMode, AppSettings};
use crate::bridge::BridgeMessage;
use tokio::sync::mpsc::UnboundedReceiver;

pub struct MainModel {
    pub(crate) window: Child<Window>,
    pub(crate) webview: Child<WebView>,
    pub(crate) app_mode: AppMode,
    pub(crate) files: Vec<String>,
    pub(crate) project_files: Vec<String>,
    pub(crate) is_generating: bool,
    pub(crate) backend_url: String,
    pub(crate) client: api::ApiClient,
    pub(crate) task_id: Option<String>,
    /// 当前对话 ID（生成/优化提交后由后端返回，历史详情也有）
    pub(crate) conversation_id: Option<String>,
    pub(crate) conversations: Vec<api::types::ConversationSummary>,
    pub(crate) selected_db: Option<api::types::DbConfig>,
    pub(crate) settings: AppSettings,
    pub(crate) show_settings: bool,
    pub(crate) bridge_rx: Option<UnboundedReceiver<BridgeMessage>>,
}
