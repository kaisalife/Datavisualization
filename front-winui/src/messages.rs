use crate::api;
use crate::bridge::BridgeMessage;

#[derive(Debug)]
pub enum MainMessage {
    Noop,
    Close,
    WindowResized,
    BridgeAction(BridgeMessage),
    TaskStarted(String),
    /// 后端提交响应返回的对话 ID（生成 / 优化都会返回）
    ConversationAssigned(String),
    /// 当前对话资产清单加载完成
    ConversationAssetsLoaded(api::types::ConversationAssetsResponse),
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
    SkillsLoaded(serde_json::Value),
    SkillLoaded(serde_json::Value),
    SkillSaved(serde_json::Value),
    SkillDeleted(serde_json::Value),
    SkillPolished(serde_json::Value),
    SkillPolishFailed(String),
    /// 技能保存/删除失败：让前端恢复按钮状态，而不是一直停在“保存中/删除中”
    SkillOperationFailed { action: String, message: String },
    ClipboardImageSaved(String),
}
