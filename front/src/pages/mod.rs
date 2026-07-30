/// 页面模块
///
/// 预留 Reactor 页面路由设计。
/// 当前 Win32 UI 在 main.rs 中实现，此模块仅保留路由枚举供未来参考。

/// 页面路由
#[allow(dead_code)]
#[derive(Debug, Clone, PartialEq)]
pub enum Page {
    /// 首页（数据源选择 + 生成）
    Home,
    /// 图表查看
    ChartView { chart_id: String },
    /// 报告查看
    ReportView { report_path: String },
}
