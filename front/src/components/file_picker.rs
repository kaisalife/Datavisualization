/// 文件选择器组件
///
/// 封装 Windows 文件选择对话框，支持多选。
/// 支持 Excel/CSV/PDF/JSON 等数据文件格式。

use std::path::PathBuf;

/// 支持的文件类型
pub const SUPPORTED_EXTENSIONS: &[&str] = &[
    "xlsx", "xls", "xlsm",
    "csv",
    "pdf",
    "json", "jsonl",
    "parquet",
    "npz",
    "zip",
];

/// 文件选择器配置
#[derive(Debug, Clone)]
pub struct FilePickerConfig {
    pub extensions: Vec<String>,
    pub multi_select: bool,
    pub title: String,
}

impl Default for FilePickerConfig {
    fn default() -> Self {
        Self {
            extensions: SUPPORTED_EXTENSIONS.iter().map(|s| s.to_string()).collect(),
            multi_select: true,
            title: "选择数据文件".to_string(),
        }
    }
}

/// 打开文件选择对话框（同步阻塞）
///
/// 使用 Win32 GetOpenFileNameW API。
pub fn pick_files(config: &FilePickerConfig) -> Vec<PathBuf> {
    use windows::Win32::UI::Controls::Dialogs::*;

    // 构建过滤器字符串（双 \0 结尾）
    // 格式："Excel Files\0*.xlsx;*.xls\0CSV Files\0*.csv\0All Files\0*.*\0\0"
    let mut filter = String::new();
    let ext_groups: Vec<(&str, Vec<&str>)> = if config.extensions.iter().any(|e| e == "xlsx" || e == "xls") {
        vec![
            ("Excel 文件", vec!["*.xlsx", "*.xls", "*.xlsm"]),
            ("CSV 文件", vec!["*.csv"]),
            ("PDF 文件", vec!["*.pdf"]),
            ("JSON 文件", vec!["*.json", "*.jsonl"]),
            ("Parquet/NPZ/ZIP", vec!["*.parquet", "*.npz", "*.zip"]),
            ("所有文件", vec!["*.*"]),
        ]
    } else {
        vec![("所有文件", vec!["*.*"])]
    };
    for (desc, exts) in &ext_groups {
        filter.push_str(desc);
        filter.push('\0');
        filter.push_str(&exts.join(";"));
        filter.push('\0');
    }
    filter.push('\0');

    let mut file_buffer = vec![0u16; 8192];
    let title: Vec<u16> = config.title.encode_utf16().chain(std::iter::once(0)).collect();
    let filter_wide: Vec<u16> = filter.encode_utf16().chain(std::iter::once(0)).collect();

    let mut ofn = OPENFILENAMEW {
        lStructSize: std::mem::size_of::<OPENFILENAMEW>() as u32,
        lpstrFile: windows::core::PWSTR(file_buffer.as_mut_ptr()),
        nMaxFile: file_buffer.len() as u32,
        lpstrFilter: windows::core::PCWSTR(filter_wide.as_ptr()),
        nFilterIndex: 1,
        lpstrTitle: windows::core::PCWSTR(title.as_ptr()),
        Flags: OFN_EXPLORER | OFN_ALLOWMULTISELECT | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST,
        ..Default::default()
    };

    let result = unsafe { GetOpenFileNameW(&mut ofn) };

    if !result.as_bool() {
        return Vec::new();
    }

    // 解析结果：直接遍历 file_buffer 按 \0 分割
    // Win32 多选格式：目录\0文件1\0文件2\0\0
    // 单选格式：完整路径\0
    let mut segments: Vec<String> = Vec::new();
    let mut start = 0;
    for i in 0..file_buffer.len() {
        if file_buffer[i] == 0 {
            if i == start {
                break; // 连续 \0，结束
            }
            let segment = String::from_utf16_lossy(&file_buffer[start..i]);
            segments.push(segment);
            start = i + 1;
        }
    }

    if segments.is_empty() {
        return Vec::new();
    }

    // 单选：只有一个段，就是完整路径
    if segments.len() == 1 {
        return vec![PathBuf::from(&segments[0])];
    }

    // 多选：第一段是目录，后续是文件名
    let dir = &segments[0];
    segments[1..]
        .iter()
        .map(|f| PathBuf::from(format!("{}\\{}", dir, f)))
        .collect()
}

/// 格式化文件大小
#[allow(dead_code)]
pub fn format_file_size(bytes: u64) -> String {
    if bytes < 1024 {
        format!("{} B", bytes)
    } else if bytes < 1024 * 1024 {
        format!("{:.1} KB", bytes as f64 / 1024.0)
    } else if bytes < 1024 * 1024 * 1024 {
        format!("{:.1} MB", bytes as f64 / (1024.0 * 1024.0))
    } else {
        format!("{:.2} GB", bytes as f64 / (1024.0 * 1024.0 * 1024.0))
    }
}

/// 获取文件扩展名
#[allow(dead_code)]
pub fn get_extension(path: &str) -> Option<String> {
    std::path::Path::new(path)
        .extension()
        .and_then(|e| e.to_str())
        .map(|s| s.to_lowercase())
}

/// 判断文件是否为支持的类型
#[allow(dead_code)]
pub fn is_supported(path: &str) -> bool {
    get_extension(path)
        .map(|ext| SUPPORTED_EXTENSIONS.contains(&ext.as_str()))
        .unwrap_or(false)
}
