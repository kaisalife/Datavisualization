/// 后端 API 客户端模块
///
/// 与 DataVisualServer Flask 后端交互：
/// - POST /api/generate-chart-with-prompt  提交图表生成任务
/// - GET  /api/chart/<chart_id>           获取图表 HTML
/// - GET  /api/task/<task_id>             查询任务状态
/// - POST /api/complete-viz-code           代码可视化补全

pub mod client;
pub mod types;

pub use client::ApiClient;
pub use types::*;
