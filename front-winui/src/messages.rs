use crate::api;
use crate::bridge::BridgeMessage;

#[derive(Debug)]
pub enum MainMessage {
    Noop,
    Close,
    WindowResized,
    BridgeAction(BridgeMessage),
    TaskStarted(String),
    TaskCompleted {
        charts: Vec<String>,
        html_files: Vec<String>,
        codes: Vec<String>,
        context_cards: Vec<serde_json::Value>,
    },
    TaskFailed(String),
    TaskCancelled,
    AppendLog(String),
    SetStatus(String),
    SetProgress { percent: f64, text: String },
    ShowToast { message: String, toast_type: String },
    OpenChartsDir(String),
    RevealChart(String),
    HistoryLoaded { conversations: Vec<api::types::ConversationSummary>, total: usize },
    ConversationDetailLoaded(api::types::ConversationDetail),
    ConversationDeleted,
    CodeCompleted(String),
    DataProfileLoaded(serde_json::Value),
    DbTablesLoaded(serde_json::Value),
    ClipboardImageSaved(String),
}
