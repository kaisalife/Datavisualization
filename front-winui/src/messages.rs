use crate::api;
use crate::bridge::BridgeMessage;

#[derive(Debug)]
pub enum MainMessage {
    Noop,
    Close,
    WindowResized,
    BridgeAction(BridgeMessage),
    TaskStarted(String),
    TaskCompleted { charts: Vec<String>, html_files: Vec<String> },
    TaskFailed(String),
    TaskCancelled,
    AppendLog(String),
    SetStatus(String),
    SetProgress { percent: f64, text: String },
    ShowToast { message: String, toast_type: String },
    OpenChartsDir(String),
    RevealChart(String),
    HistoryLoaded(Vec<api::types::ConversationSummary>),
    ConversationDetailLoaded(api::types::ConversationDetail),
    ConversationDeleted,
    CodeCompleted(String),
}
