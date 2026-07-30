/// WebView 嵌入模块
///
/// 在窗口中展示后端生成的 ECharts HTML 图表。
///
/// 当前方案：使用 ShellExecuteW 调用系统默认浏览器打开 URL。
/// 后续方案：通过 WebView2 COM 互操作嵌入到 Win32 子窗口中。
///
/// WebView2 COM 互操作需要：
/// 1. 安装 Microsoft Edge WebView2 Runtime
/// 2. 通过 CoCreateInstance 创建 CoreWebView2Environment
/// 3. CreateCoreWebView2ControllerAsync 嵌入到 HWND
/// 4. Navigate(url) 加载图表页面

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;

use windows::core::PCWSTR;
use windows::Win32::UI::Shell::ShellExecuteW;
use windows::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

/// 用系统默认浏览器打开 URL
///
/// 当前阶段的临时方案。
/// 后续接入 WebView2 后，将在窗口内嵌入显示。
pub fn open_url(url: &str) -> bool {
    let wide_url: Vec<u16> = OsStr::new(url)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    let result = unsafe {
        ShellExecuteW(
            None,
            windows::core::w!("open"),
            PCWSTR(wide_url.as_ptr()),
            None,
            None,
            SW_SHOWNORMAL,
        )
    };

    let hinst = unsafe { result.0 };
    // ShellExecuteW 返回 HINSTANCE > 32 表示成功
    hinst as usize > 32
}

/// 在指定窗口中嵌入 WebView2（预留接口）
///
/// TODO: 实现 WebView2 COM 互操作
///
/// 步骤：
/// 1. CoCreateInstance(CLSID_CoreWebView2Environment)
/// 2. CreateCoreWebView2EnvironmentWithOptions(callback)
/// 3. Environment->CreateCoreWebView2Controller(hwnd, callback)
/// 4. Controller->get_CoreWebView2() -> Navigate(url)
///
/// 需要安装 WebView2 COM 互操作 crate 或手动定义 COM 接口。
pub fn embed_webview2(_parent_hwnd: isize, _url: &str) -> Result<(), String> {
    // 当前阶段：未实现，返回提示
    Err("WebView2 嵌入尚未实现，请使用 open_url() 替代".to_string())
}

/// 构建图表查看 URL
///
/// 拼接后端 base_url 和 chart_id，生成可直接打开的 URL。
#[allow(dead_code)]
pub fn build_chart_url(base_url: &str, chart_id: &str) -> String {
    format!(
        "{}/api/chart/{}",
        base_url.trim_end_matches('/'),
        chart_id
    )
}

/// 构建报告查看 URL
#[allow(dead_code)]
pub fn build_report_url(base_url: &str, report_path: &str) -> String {
    // 报告路径可能是本地文件或 URL
    if report_path.starts_with("http") {
        report_path.to_string()
    } else {
        format!(
            "{}/reports/{}",
            base_url.trim_end_matches('/'),
            report_path.trim_start_matches('/')
        )
    }
}
