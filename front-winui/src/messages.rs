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
    AppendLog(String),
    SetStatus(String),
    HistoryLoaded(Vec<api::types::ConversationSummary>),
    ConversationDetailLoaded(api::types::ConversationDetail),
    ConversationDeleted,
    CodeCompleted(String),
}
