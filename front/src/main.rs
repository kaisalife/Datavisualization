// DataVisualServer 前端入口
//
// 使用 Win32 API 创建原生窗口，预留 WinUI 3 / Reactor 接入点。
// 当 Windows Reactor 发布到 crates.io 后，可无缝切换到声明式 UI。

mod api;
mod components;
mod pages;
mod state;

use std::sync::Mutex;
use windows::core::*;
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM, HINSTANCE};
use windows::Win32::Graphics::Gdi::*;
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::Com::*;
use windows::Win32::UI::Controls::*;
use windows::Win32::UI::WindowsAndMessaging::*;
use windows::Win32::UI::Shell::{DragAcceptFiles, DragQueryFileW, DragFinish, HDROP};

const WINDOW_WIDTH: i32 = 1200;
const WINDOW_HEIGHT: i32 = 800;

// 控件 ID
const IDC_BTN_PICK_FILE: u16 = 101;
const IDC_BTN_GENERATE: u16 = 102;
const IDC_EDIT_PROMPT: u16 = 103;
const IDC_STATIC_STATUS: u16 = 104;
const IDC_LIST_FILES: u16 = 105;
const IDC_EDIT_DB_CONFIG: u16 = 106;
const IDC_COMBO_VIZ_MODE: u16 = 107;
const IDC_BTN_REMOVE_FILE: u16 = 108;
const IDC_BTN_CLEAR: u16 = 109;
const IDC_EDIT_LOG: u16 = 110;
const IDC_LIST_HISTORY: u16 = 111;
const IDC_BTN_HISTORY: u16 = 112;
const IDC_BTN_RESUBMIT: u16 = 113;
const IDC_BTN_CANCEL: u16 = 114;
const IDC_BTN_DELETE_CONV: u16 = 115;
const IDC_BTN_CONFIG: u16 = 116;
const IDC_BTN_VIZ_CODE: u16 = 117;

// 全局状态（简单方案，后续可改为线程安全）
struct AppData {
    selected_files: Vec<String>,
    api_client: Option<api::ApiClient>,
    conversations: Vec<api::ConversationSummary>,
    current_task_id: Option<String>,
    // 高级参数
    model_url: Option<String>,
    model_type: Option<String>,
    model_api_key: Option<String>,
    mcp_prompt: Option<String>,
    skill_prompt: Option<String>,
}
static APP_DATA: Mutex<Option<AppData>> = Mutex::new(None);

/// 窗口过程回调
extern "system" fn window_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_CREATE => {
            let h_instance = unsafe { GetModuleHandleW(None) }.unwrap_or_default();

            // 选择文件按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("选择文件"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    10, 10, 120, 36,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_PICK_FILE as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 生成图表按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("生成图表"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    140, 10, 120, 36,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_GENERATE as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 可视化模式下拉框
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("COMBOBOX"),
                    w!(""),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | CBS_DROPDOWNLIST as u32 | WS_VSCROLL.0),
                    270, 10, 120, 200,
                    Some(hwnd),
                    Some(HMENU(IDC_COMBO_VIZ_MODE as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };
            // 添加选项
            let h_combo = unsafe { GetDlgItem(Some(hwnd), IDC_COMBO_VIZ_MODE as i32) }.unwrap_or_default();
            if !h_combo.is_invalid() {
                for item in [w!("auto"), w!("chart"), w!("scientific")] {
                    unsafe {
                        let _ = SendMessageW(h_combo, CB_ADDSTRING, Some(WPARAM(0)), Some(LPARAM(item.as_ptr() as isize)));
                    }
                }
                // 默认选中 auto
                unsafe {
                    let _ = SendMessageW(h_combo, CB_SETCURSEL, Some(WPARAM(0)), Some(LPARAM(0)));
                }
            }

            // 删除选中文件按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("删除选中"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    400, 10, 100, 36,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_REMOVE_FILE as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 清空按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("清空"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    510, 10, 80, 36,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_CLEAR as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 取消按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("取消任务"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    600, 10, 100, 36,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_CANCEL as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 配置按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("配置"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    710, 10, 60, 36,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_CONFIG as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 代码补全按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("代码补全"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    775, 10, 70, 36,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_VIZ_CODE as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 提示词编辑框
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("EDIT"),
                    w!("请输入可视化需求，例如：画一个柱状图展示销售额趋势"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | ES_AUTOHSCROLL as u32 | WS_BORDER.0),
                    10, 56, 700, 32,
                    Some(hwnd),
                    Some(HMENU(IDC_EDIT_PROMPT as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 状态文本
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("STATIC"),
                    w!("就绪 - 请选择数据文件并输入可视化需求"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0),
                    10, 96, 700, 24,
                    Some(hwnd),
                    Some(HMENU(IDC_STATIC_STATUS as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 文件列表
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("LISTBOX"),
                    w!(""),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | LBS_STANDARD as u32 | WS_VSCROLL.0),
                    10, 130, 560, 120,
                    Some(hwnd),
                    Some(HMENU(IDC_LIST_FILES as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 数据库配置标签
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("STATIC"),
                    w!("数据库配置（可选，JSON 格式，留空则使用上传文件）"),
                    WS_CHILD | WS_VISIBLE | WINDOW_STYLE(0),
                    580, 130, 400, 20,
                    Some(hwnd),
                    Some(HMENU(std::ptr::null_mut())),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 数据库配置编辑框（多行）
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("EDIT"),
                    w!(""),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | ES_MULTILINE as u32 | WS_VSCROLL.0 | WS_BORDER.0 | ES_AUTOVSCROLL as u32),
                    580, 155, 400, 175,
                    Some(hwnd),
                    Some(HMENU(IDC_EDIT_DB_CONFIG as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 历史对话标签
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("STATIC"),
                    w!("历史对话"),
                    WS_CHILD | WS_VISIBLE | WINDOW_STYLE(0),
                    10, 255, 200, 20,
                    Some(hwnd),
                    Some(HMENU(std::ptr::null_mut())),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 历史对话列表
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("LISTBOX"),
                    w!(""),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | LBS_STANDARD as u32 | WS_VSCROLL.0),
                    10, 275, 560, 70,
                    Some(hwnd),
                    Some(HMENU(IDC_LIST_HISTORY as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 加载历史按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("加载历史"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    10, 350, 80, 25,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_HISTORY as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 重提提示词按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("重提提示词"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    95, 350, 90, 25,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_RESUBMIT as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 删除对话按钮
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("删除对话"),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | BS_PUSHBUTTON as u32),
                    265, 350, 80, 25,
                    Some(hwnd),
                    Some(HMENU(IDC_BTN_DELETE_CONV as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 日志面板标签
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("STATIC"),
                    w!("对话日志"),
                    WS_CHILD | WS_VISIBLE | WINDOW_STYLE(0),
                    200, 355, 200, 20,
                    Some(hwnd),
                    Some(HMENU(std::ptr::null_mut())),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 日志面板（多行只读编辑框）
            let _ = unsafe {
                CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("EDIT"),
                    w!(""),
                    WINDOW_STYLE(WS_CHILD.0 | WS_VISIBLE.0 | ES_MULTILINE as u32 | ES_READONLY as u32 | WS_VSCROLL.0 | WS_BORDER.0 | ES_AUTOVSCROLL as u32),
                    10, 380, 970, 180,
                    Some(hwnd),
                    Some(HMENU(IDC_EDIT_LOG as usize as *mut core::ffi::c_void)),
                    Some(HINSTANCE(h_instance.0)),
                    None,
                )
            };

            // 初始化 API 客户端
            let base_url = std::env::var("BACKEND_URL")
                .unwrap_or_else(|_| "http://localhost:5000".to_string());
            let api_key = std::env::var("API_KEY")
                .unwrap_or_else(|_| "datavisual-api-key".to_string());
            let client = api::ApiClient::new(&base_url, &api_key);

            // 从环境变量读取高级参数
            let model_url = std::env::var("MODEL_URL").ok().filter(|s| !s.is_empty());
            let model_type = std::env::var("MODEL_TYPE").ok().filter(|s| !s.is_empty());
            let model_api_key = std::env::var("MODEL_API_KEY").ok().filter(|s| !s.is_empty());
            let mcp_prompt = std::env::var("MCP_PROMPT").ok().filter(|s| !s.is_empty());
            let skill_prompt = std::env::var("SKILL_PROMPT").ok().filter(|s| !s.is_empty());

            let mut data = APP_DATA.lock().unwrap();
            *data = Some(AppData {
                selected_files: Vec::new(),
                api_client: Some(client),
                conversations: Vec::new(),
                current_task_id: None,
                model_url,
                model_type,
                model_api_key,
                mcp_prompt,
                skill_prompt,
            });

            // 设置字体（默认 GUI 字体）
            let h_font = unsafe {
                CreateFontW(
                    16, 0, 0, 0, FW_NORMAL.0 as i32, 0, 0, 0,
                    DEFAULT_CHARSET,
                    OUT_DEFAULT_PRECIS,
                    CLIP_DEFAULT_PRECIS,
                    DEFAULT_QUALITY,
                    DEFAULT_PITCH.0 as u32,
                    w!("Microsoft YaHei UI"),
                )
            };
            let ids = [IDC_BTN_PICK_FILE, IDC_BTN_GENERATE, IDC_EDIT_PROMPT,
                       IDC_STATIC_STATUS, IDC_LIST_FILES, IDC_EDIT_DB_CONFIG,
                       IDC_COMBO_VIZ_MODE, IDC_BTN_REMOVE_FILE, IDC_BTN_CLEAR,
                       IDC_EDIT_LOG, IDC_LIST_HISTORY, IDC_BTN_HISTORY,
                       IDC_BTN_RESUBMIT, IDC_BTN_CANCEL, IDC_BTN_DELETE_CONV,
                       IDC_BTN_CONFIG, IDC_BTN_VIZ_CODE];
            for id in ids {
                let hctrl = unsafe { GetDlgItem(Some(hwnd), id as i32) }.unwrap_or_default();
                if !hctrl.is_invalid() {
                    unsafe { let _ = SendMessageW(hctrl, WM_SETFONT, Some(WPARAM(h_font.0 as usize)), Some(LPARAM(1))); }
                }
            }

            LRESULT(0)
        }

        WM_COMMAND => {
            let control_id = loword(wparam.0 as u32);
            let notification = hiword(wparam.0 as u32);

            // 历史对话列表双击
            if control_id == IDC_LIST_HISTORY && notification == LBN_DBLCLK as u16 {
                on_view_conversation(hwnd);
                return LRESULT(0);
            }

            if notification == BN_CLICKED as u16 {
                match control_id {
                    IDC_BTN_PICK_FILE => {
                        on_pick_file(hwnd);
                    }
                    IDC_BTN_GENERATE => {
                        on_generate(hwnd);
                    }
                    IDC_BTN_REMOVE_FILE => {
                        on_remove_file(hwnd);
                    }
                    IDC_BTN_CLEAR => {
                        on_clear_files(hwnd);
                    }
                    IDC_BTN_HISTORY => {
                        on_load_history(hwnd);
                    }
                    IDC_BTN_RESUBMIT => {
                        on_resubmit_prompt(hwnd);
                    }
                    IDC_BTN_DELETE_CONV => {
                        on_delete_conversation(hwnd);
                    }
                    IDC_BTN_CANCEL => {
                        on_cancel(hwnd);
                    }
                    IDC_BTN_CONFIG => {
                        on_show_config(hwnd);
                    }
                    IDC_BTN_VIZ_CODE => {
                        on_viz_code(hwnd);
                    }
                    _ => {}
                }
            }
            LRESULT(0)
        }

        WM_SIZE => {
            let width = loword(lparam.0 as u32) as i32;
            let height = hiword(lparam.0 as u32) as i32;
            let half_w = width / 2 - 15;
            // 调整文件列表框（左半边，高度 120）
            let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_FILES as i32) }.unwrap_or_default();
            if !h_list.is_invalid() {
                unsafe {
                    let _ = MoveWindow(h_list, 10, 130, half_w, 120, true);
                }
            }
            // 调整历史对话列表（左半边，文件列表下方）
            let h_history = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_HISTORY as i32) }.unwrap_or_default();
            if !h_history.is_invalid() {
                unsafe {
                    let _ = MoveWindow(h_history, 10, 275, half_w, 70, true);
                }
            }
            // 调整 db_config 编辑框（右半边，固定高度 175）
            let h_db = unsafe { GetDlgItem(Some(hwnd), IDC_EDIT_DB_CONFIG as i32) }.unwrap_or_default();
            if !h_db.is_invalid() {
                unsafe {
                    let _ = MoveWindow(h_db, width / 2 + 5, 155, half_w, 175, true);
                }
            }
            // 调整提示词编辑框宽度
            let h_edit = unsafe { GetDlgItem(Some(hwnd), IDC_EDIT_PROMPT as i32) }.unwrap_or_default();
            if !h_edit.is_invalid() {
                unsafe {
                    let _ = MoveWindow(h_edit, 10, 56, width - 20, 32, true);
                }
            }
            // 调整状态文本宽度
            let h_status = unsafe { GetDlgItem(Some(hwnd), IDC_STATIC_STATUS as i32) }.unwrap_or_default();
            if !h_status.is_invalid() {
                unsafe {
                    let _ = MoveWindow(h_status, 10, 96, width - 20, 24, true);
                }
            }
            // 调整日志面板（底部全宽）
            let h_log = unsafe { GetDlgItem(Some(hwnd), IDC_EDIT_LOG as i32) }.unwrap_or_default();
            if !h_log.is_invalid() {
                unsafe {
                    let log_h = height - 400;
                    if log_h > 50 {
                        let _ = MoveWindow(h_log, 10, 380, width - 20, log_h, true);
                    }
                }
            }
            LRESULT(0)
        }

        WM_DROPFILES => {
            let h_drop = HDROP(wparam.0 as *mut _);
            let file_count = unsafe { DragQueryFileW(h_drop, 0xFFFFFFFF, None) };

            for i in 0..file_count {
                // 获取文件路径长度
                let len = unsafe { DragQueryFileW(h_drop, i, None) };
                if len == 0 {
                    continue;
                }
                // 获取文件路径
                let mut buffer = vec![0u16; (len as usize) + 1];
                unsafe {
                    let _ = DragQueryFileW(h_drop, i, Some(buffer.as_mut_slice()));
                }
                let path = String::from_utf16_lossy(&buffer[..buffer.iter().position(|&c| c == 0).unwrap_or(buffer.len())]);

                // 添加到全局状态
                {
                    let mut data = APP_DATA.lock().unwrap();
                    if let Some(app_data) = data.as_mut() {
                        if !app_data.selected_files.contains(&path) {
                            app_data.selected_files.push(path.clone());
                        }
                    }
                }
            }

            unsafe { DragFinish(h_drop); }

            // 刷新列表框
            refresh_file_list(hwnd);

            let count = {
                let data = APP_DATA.lock().unwrap();
                data.as_ref().map(|d| d.selected_files.len()).unwrap_or(0)
            };
            set_status_text(hwnd, &format!("拖拽添加完成，共 {} 个文件", count));

            LRESULT(0)
        }

        WM_PAINT => {
            let mut ps = PAINTSTRUCT::default();
            let hdc = unsafe { BeginPaint(hwnd, &mut ps) };
            if !hdc.is_invalid() {
                unsafe { let _ = EndPaint(hwnd, &ps); };
            }
            LRESULT(0)
        }

        WM_DESTROY => {
            unsafe { PostQuitMessage(0) };
            LRESULT(0)
        }

        _ => unsafe { DefWindowProcW(hwnd, msg, wparam, lparam) },
    }
}

/// 处理"选择文件"按钮点击
fn on_pick_file(hwnd: HWND) {
    let config = components::file_picker::FilePickerConfig::default();
    let files = components::file_picker::pick_files(&config);

    if files.is_empty() {
        return;
    }

    // 更新全局状态（追加模式，去重）
    {
        let mut data = APP_DATA.lock().unwrap();
        if let Some(app_data) = data.as_mut() {
            for f in &files {
                if let Some(s) = f.to_str() {
                    if !app_data.selected_files.contains(&s.to_string()) {
                        app_data.selected_files.push(s.to_string());
                    }
                }
            }
        }
    }

    // 刷新列表框
    refresh_file_list(hwnd);

    // 更新状态
    let total = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref().map(|d| d.selected_files.len()).unwrap_or(0)
    };
    let status = format!("已选择 {} 个文件（共 {} 个）", files.len(), total);
    set_status_text(hwnd, &status);
}

/// 刷新文件列表框
fn refresh_file_list(hwnd: HWND) {
    let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_FILES as i32) }.unwrap_or_default();
    if h_list.is_invalid() {
        return;
    }

    unsafe {
        let _ = SendMessageW(h_list, LB_RESETCONTENT, Some(WPARAM(0)), Some(LPARAM(0)));
    }

    let data = APP_DATA.lock().unwrap();
    if let Some(app_data) = data.as_ref() {
        for f in &app_data.selected_files {
            let wide: Vec<u16> = f.encode_utf16().chain(std::iter::once(0)).collect();
            unsafe {
                let _ = SendMessageW(
                    h_list,
                    LB_ADDSTRING,
                    Some(WPARAM(0)),
                    Some(LPARAM(wide.as_ptr() as isize)),
                );
            }
        }
    }
}

/// 处理"删除选中"按钮点击
fn on_remove_file(hwnd: HWND) {
    let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_FILES as i32) }.unwrap_or_default();
    if h_list.is_invalid() {
        return;
    }

    // 获取选中项索引
    let sel = unsafe { SendMessageW(h_list, LB_GETCURSEL, Some(WPARAM(0)), Some(LPARAM(0))) };
    if sel.0 < 0 {
        set_status_text(hwnd, "请先在列表中选择要删除的文件");
        return;
    }

    let idx = sel.0 as usize;

    // 从全局状态中删除
    {
        let mut data = APP_DATA.lock().unwrap();
        if let Some(app_data) = data.as_mut() {
            if idx < app_data.selected_files.len() {
                app_data.selected_files.remove(idx);
            }
        }
    }

    // 从列表框中删除
    unsafe {
        let _ = SendMessageW(h_list, LB_DELETESTRING, Some(WPARAM(sel.0 as usize)), Some(LPARAM(0)));
    }

    set_status_text(hwnd, "已删除选中文件");
}

/// 处理"清空"按钮点击
fn on_clear_files(hwnd: HWND) {
    // 清空全局状态
    {
        let mut data = APP_DATA.lock().unwrap();
        if let Some(app_data) = data.as_mut() {
            app_data.selected_files.clear();
        }
    }

    // 清空列表框
    let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_FILES as i32) }.unwrap_or_default();
    if !h_list.is_invalid() {
        unsafe {
            let _ = SendMessageW(h_list, LB_RESETCONTENT, Some(WPARAM(0)), Some(LPARAM(0)));
        }
    }

    set_status_text(hwnd, "已清空文件列表");
}

/// 处理"生成图表"按钮点击
fn on_generate(hwnd: HWND) {
    // 读取提示词
    let prompt = get_edit_text(hwnd, IDC_EDIT_PROMPT);
    if prompt.is_empty() {
        set_status_text(hwnd, "请输入可视化需求");
        return;
    }

    // 检查文件
    let files: Vec<String> = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref()
            .map(|d| d.selected_files.clone())
            .unwrap_or_default()
    };

    // 读取数据库配置（可选）
    let db_config_text = get_edit_text(hwnd, IDC_EDIT_DB_CONFIG);
    let has_db_config = !db_config_text.trim().is_empty();

    // 读取可视化模式
    let viz_mode = get_combo_selection(hwnd, IDC_COMBO_VIZ_MODE);

    // 文件和 db_config 至少提供其一
    if files.is_empty() && !has_db_config {
        set_status_text(hwnd, "请选择数据文件或输入数据库配置");
        return;
    }

    set_status_text(hwnd, "正在提交任务...");
    clear_log(hwnd);
    append_log(hwnd, &format!("提示词: {}", prompt));
    append_log(hwnd, &format!("文件数: {}, db_config: {}", files.len(), if has_db_config { "有" } else { "无" }));
    append_log(hwnd, &format!("可视化模式: {:?}", viz_mode));
    append_log(hwnd, "正在提交任务到后端...");

    // 获取 API 客户端
    let client = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref().and_then(|d| d.api_client.clone())
    };

    if let Some(client) = client {
        // 使用前面已读取的数据库配置
        let db_config = if has_db_config {
            Some(db_config_text.trim().to_string())
        } else {
            None
        };

        // 构建请求
        // 从 APP_DATA 读取高级参数
        let (model_url, model_type, model_api_key, mcp_prompt, skill_prompt) = {
            let data = APP_DATA.lock().unwrap();
            data.as_ref().map(|d| (
                d.model_url.clone(),
                d.model_type.clone(),
                d.model_api_key.clone(),
                d.mcp_prompt.clone(),
                d.skill_prompt.clone(),
            )).unwrap_or((None, None, None, None, None))
        };

        let request = api::GenerateChartRequest {
            file_paths: files,
            user_prompt: prompt,
            viz_mode,
            db_config,
            config: None,
            model_url,
            model_type,
            model_api_key,
            mcp_prompt,
            skill_prompt,
        };

        // 保存窗口句柄供工作线程更新 UI
        let hwnd_ptr = hwnd.0 as isize;

        // 异步提交 + 轮询 + 打开图表
        std::thread::spawn(move || {
            let rt = match tokio::runtime::Runtime::new() {
                Ok(rt) => rt,
                Err(e) => {
                    tracing::error!("创建 tokio 运行时失败: {}", e);
                    return;
                }
            };

            // 1. 提交任务（async）
            let submit_result = rt.block_on(async {
                client.generate_chart(&request).await
            });

            match submit_result {
                Ok(resp) => {
                    tracing::info!("任务已提交: {}", resp.task_id);
                    append_log_ptr(hwnd_ptr, &format!("✅ 任务已提交: {}", &resp.task_id[..8]));
                    // 保存当前 task_id 供取消使用
                    {
                        let mut data = APP_DATA.lock().unwrap();
                        if let Some(app_data) = data.as_mut() {
                            app_data.current_task_id = Some(resp.task_id.clone());
                        }
                    }
                    update_status(hwnd_ptr, &format!("任务已提交: {}，正在生成...", &resp.task_id[..8]));

                    // 2. WebSocket 等待任务完成（同步）
                    append_log_ptr(hwnd_ptr, "🔗 连接 WebSocket 等待结果...");
                    let ws_url = client.ws_task_url(&resp.task_id);
                    let task_result = wait_for_completion_ws(&ws_url, hwnd_ptr, &resp.task_id);

                    // 如果 WebSocket 失败，回退到轮询
                    let task_result = match task_result {
                        Some(task) => Some(task),
                        None => {
                            append_log_ptr(hwnd_ptr, "⚠️ 回退到轮询模式...");
                            let poll_result = rt.block_on(async {
                                client.poll_task_until_done(&resp.task_id, |i| {
                                    append_log_ptr(hwnd_ptr, &format!("⏳ 生成中... 已等待 {}s", i));
                                    update_status(hwnd_ptr, &format!("生成中... 已等待 {}s", i));
                                }).await
                            });

                            match poll_result {
                                Ok(task) => {
                                    append_log_ptr(hwnd_ptr, "✅ 后端任务完成");
                                    Some(task)
                                }
                                Err(e) => {
                                    let msg = format!("{}", e);
                                    append_log_ptr(hwnd_ptr, &format!("❌ {}", msg));
                                    update_status(hwnd_ptr, &format!("❌ {}", msg));
                                    clear_current_task();
                                    return;
                                }
                            }
                        }
                    };

                    // 3. 处理结果
                    match task_result {
                        Some(task) if task.status == api::TaskStatus::Failed => {
                            clear_current_task();
                        }
                        Some(task) => {
                            if let Some(result) = &task.result {
                                let chart_count = result.html_file_paths.len();
                                append_log_ptr(hwnd_ptr, &format!("📊 共生成 {} 张图表", chart_count));

                                // 展示后端 AgentLogs
                                if !result.agent_logs.is_empty() {
                                    append_log_ptr(hwnd_ptr, "── 后端执行日志 ──");
                                    for log_line in &result.agent_logs {
                                        append_log_ptr(hwnd_ptr, log_line);
                                    }
                                    append_log_ptr(hwnd_ptr, "── 日志结束 ──");
                                }

                                update_status(hwnd_ptr, &format!("生成完成！共 {} 张图表，正在打开...", chart_count));

                                // 4. 打开每张图表
                                for (idx, file_path) in result.html_file_paths.iter().enumerate() {
                                    let chart_id = std::path::Path::new(file_path)
                                        .file_name()
                                        .and_then(|n| n.to_str())
                                        .unwrap_or(file_path);
                                    let url = client.chart_url(chart_id);
                                    append_log_ptr(hwnd_ptr, &format!("📂 打开图表 {}/{}: {}", idx + 1, chart_count, chart_id));

                                    if !components::webview::open_url(&url) {
                                        append_log_ptr(hwnd_ptr, &format!("⚠️ 打开失败: {}", url));
                                    }
                                }

                                append_log_ptr(hwnd_ptr, "✅ 全部完成！");
                                update_status(hwnd_ptr, &format!("✅ 完成！已生成 {} 张图表", chart_count));
                                clear_current_task();
                            } else {
                                append_log_ptr(hwnd_ptr, "⚠️ 任务完成但无结果");
                                update_status(hwnd_ptr, "任务完成但无结果");
                                clear_current_task();
                            }
                        }
                        None => {
                            append_log_ptr(hwnd_ptr, "❌ 任务超时（5 分钟）");
                            update_status(hwnd_ptr, "❌ 任务超时（5 分钟）");
                            clear_current_task();
                        }
                    }
                }
                Err(e) => {
                    tracing::error!("提交失败: {}", e);
                    append_log_ptr(hwnd_ptr, &format!("❌ 提交失败: {}", e));
                    update_status(hwnd_ptr, &format!("❌ 提交失败: {}", e));
                    clear_current_task();
                }
            }
        });

        set_status_text(hwnd, "正在提交任务...");
    } else {
        set_status_text(hwnd, "API 客户端未初始化");
    }
}

/// 清除当前任务 ID
fn clear_current_task() {
    let mut data = APP_DATA.lock().unwrap();
    if let Some(app_data) = data.as_mut() {
        app_data.current_task_id = None;
    }
}

/// 处理"取消任务"按钮点击
fn on_cancel(hwnd: HWND) {
    let (client, task_id) = {
        let data = APP_DATA.lock().unwrap();
        let client = data.as_ref().and_then(|d| d.api_client.clone());
        let task_id = data.as_ref().and_then(|d| d.current_task_id.clone());
        (client, task_id)
    };

    let task_id = match task_id {
        Some(id) => id,
        None => {
            set_status_text(hwnd, "没有正在执行的任务");
            return;
        }
    };

    let client = match client {
        Some(c) => c,
        None => {
            set_status_text(hwnd, "API 客户端未初始化");
            return;
        }
    };

    set_status_text(hwnd, "正在取消任务...");
    append_log(hwnd, &format!("正在取消任务 {}...", &task_id[..8]));

    let hwnd_ptr = hwnd.0 as isize;
    std::thread::spawn(move || {
        let rt = match tokio::runtime::Runtime::new() {
            Ok(rt) => rt,
            Err(_) => return,
        };

        rt.block_on(async {
            let url = format!("{}/api/task/{}/cancel", client.base_url(), task_id);
            match client.raw_post(&url).await {
                Ok(_) => {
                    append_log_ptr(hwnd_ptr, "✅ 取消请求已发送");
                    update_status(hwnd_ptr, "任务取消中...");
                }
                Err(e) => {
                    append_log_ptr(hwnd_ptr, &format!("❌ 取消失败: {}", e));
                    update_status(hwnd_ptr, &format!("❌ 取消失败: {}", e));
                }
            }
        });
    });
}

/// 处理"配置"按钮点击 - 在日志面板中显示当前配置
fn on_show_config(hwnd: HWND) {
    let data = APP_DATA.lock().unwrap();
    if let Some(app_data) = data.as_ref() {
        clear_log(hwnd);
        append_log(hwnd, "═══════════════════════════════════════");
        append_log(hwnd, "  当前配置（通过环境变量设置）");
        append_log(hwnd, "═══════════════════════════════════════");
        append_log(hwnd, &format!("  BACKEND_URL: {}", std::env::var("BACKEND_URL").unwrap_or_else(|_| "http://localhost:5000".to_string())));
        append_log(hwnd, &format!("  MODEL_URL: {}", app_data.model_url.as_deref().unwrap_or("(未设置)")));
        append_log(hwnd, &format!("  MODEL_TYPE: {}", app_data.model_type.as_deref().unwrap_or("(未设置)")));
        append_log(hwnd, &format!("  MODEL_API_KEY: {}", if app_data.model_api_key.is_some() { "***（已设置）" } else { "(未设置)" }));
        append_log(hwnd, &format!("  MCP_PROMPT: {}", if app_data.mcp_prompt.is_some() { format!("{}...", app_data.mcp_prompt.as_ref().unwrap().chars().take(30).collect::<String>()) } else { "(未设置)".to_string() }));
        append_log(hwnd, &format!("  SKILL_PROMPT: {}", if app_data.skill_prompt.is_some() { format!("{}...", app_data.skill_prompt.as_ref().unwrap().chars().take(30).collect::<String>()) } else { "(未设置)".to_string() }));
        append_log(hwnd, "═══════════════════════════════════════");
        append_log(hwnd, "提示: 通过环境变量配置以上参数后重启程序");
    }
}

/// 处理"代码补全"按钮点击
///
/// 将当前选中的文件和提示词发送到后端 complete-viz-code API，
/// 在日志面板中展示返回的代码片段、解释和依赖库。
fn on_viz_code(hwnd: HWND) {
    // 读取提示词
    let prompt = get_edit_text(hwnd, IDC_EDIT_PROMPT);
    if prompt.trim().is_empty() {
        set_status_text(hwnd, "请输入提示词");
        return;
    }

    // 读取文件和高级参数
    let (files, model_url, model_type, model_api_key) = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref().map(|d| (
            d.selected_files.clone(),
            d.model_url.clone(),
            d.model_type.clone(),
            d.model_api_key.clone(),
        )).unwrap_or((Vec::new(), None, None, None))
    };

    if files.is_empty() {
        set_status_text(hwnd, "请先选择代码文件");
        return;
    }

    let client = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref().and_then(|d| d.api_client.clone())
    };

    let client = match client {
        Some(c) => c,
        None => {
            set_status_text(hwnd, "API 客户端未初始化");
            return;
        }
    };

    set_status_text(hwnd, "正在请求代码补全...");
    append_log(hwnd, &format!("📝 代码补全请求: {} 个文件, 提示词: {}", files.len(), &prompt[..prompt.len().min(40)]));

    let request = api::CompleteVizCodeRequest {
        code_file_paths: files,
        user_prompt: prompt,
        scientific_lib: None,
        model_url,
        model_type,
        model_api_key,
    };

    let hwnd_ptr = hwnd.0 as isize;
    std::thread::spawn(move || {
        let rt = match tokio::runtime::Runtime::new() {
            Ok(rt) => rt,
            Err(_) => return,
        };

        rt.block_on(async {
            match client.complete_viz_code(&request).await {
                Ok(resp) => {
                    append_log_ptr(hwnd_ptr, "✅ 代码补全完成");
                    if !resp.libs.is_empty() {
                        append_log_ptr(hwnd_ptr, &format!("📦 依赖库: {}", resp.libs.join(", ")));
                    }
                    if !resp.explanation.is_empty() {
                        append_log_ptr(hwnd_ptr, "── 解释 ──");
                        for line in resp.explanation.lines() {
                            append_log_ptr(hwnd_ptr, line);
                        }
                    }
                    if !resp.snippet.is_empty() {
                        append_log_ptr(hwnd_ptr, "── 代码片段 ──");
                        for line in resp.snippet.lines() {
                            append_log_ptr(hwnd_ptr, line);
                        }
                        append_log_ptr(hwnd_ptr, "── 结束 ──");
                    }
                    update_status(hwnd_ptr, "代码补全完成");
                }
                Err(e) => {
                    append_log_ptr(hwnd_ptr, &format!("❌ 代码补全失败: {}", e));
                    update_status(hwnd_ptr, &format!("❌ 代码补全失败: {}", e));
                }
            }
        });
    });
}

/// 向日志面板追加一行（主线程调用）
fn append_log(hwnd: HWND, text: &str) {
    let h_log = unsafe { GetDlgItem(Some(hwnd), IDC_EDIT_LOG as i32) }.unwrap_or_default();
    if h_log.is_invalid() {
        return;
    }

    // 获取当前文本长度
    let len = unsafe { SendMessageW(h_log, WM_GETTEXTLENGTH, Some(WPARAM(0)), Some(LPARAM(0))) };
    
    // 追加带时间戳的日志行
    let timestamp = chrono::Local::now().format("%H:%M:%S").to_string();
    let line = format!("[{}] {}\r\n", timestamp, text);
    let wide: Vec<u16> = line.encode_utf16().chain(std::iter::once(0)).collect();

    unsafe {
        // 选中文本末尾
        let _ = SendMessageW(h_log, EM_SETSEL, Some(WPARAM(len.0 as usize)), Some(LPARAM(len.0 as isize)));
        // 替换选中（在末尾追加）
        let _ = SendMessageW(
            h_log,
            EM_REPLACESEL,
            Some(WPARAM(0)),
            Some(LPARAM(wide.as_ptr() as isize)),
        );
    }
}

/// 向日志面板追加一行（工作线程调用，跨线程安全）
fn append_log_ptr(hwnd_ptr: isize, text: &str) {
    let hwnd = HWND(hwnd_ptr as *mut _);
    let h_log = unsafe { GetDlgItem(Some(hwnd), IDC_EDIT_LOG as i32) }.unwrap_or_default();
    if h_log.is_invalid() {
        return;
    }

    let len = unsafe { SendMessageW(h_log, WM_GETTEXTLENGTH, Some(WPARAM(0)), Some(LPARAM(0))) };
    
    let timestamp = chrono::Local::now().format("%H:%M:%S").to_string();
    let line = format!("[{}] {}\r\n", timestamp, text);
    let wide: Vec<u16> = line.encode_utf16().chain(std::iter::once(0)).collect();

    unsafe {
        let _ = SendMessageW(h_log, EM_SETSEL, Some(WPARAM(len.0 as usize)), Some(LPARAM(len.0 as isize)));
        let _ = SendMessageW(
            h_log,
            EM_REPLACESEL,
            Some(WPARAM(0)),
            Some(LPARAM(wide.as_ptr() as isize)),
        );
    }
}

/// 清空日志面板
fn clear_log(hwnd: HWND) {
    let h_log = unsafe { GetDlgItem(Some(hwnd), IDC_EDIT_LOG as i32) }.unwrap_or_default();
    if !h_log.is_invalid() {
        let empty: Vec<u16> = vec![0];
        unsafe {
            let _ = SendMessageW(h_log, WM_SETTEXT, Some(WPARAM(0)), Some(LPARAM(empty.as_ptr() as isize)));
        }
    }
}

/// 设置状态文本
fn set_status_text(hwnd: HWND, text: &str) {
    let h_status = unsafe { GetDlgItem(Some(hwnd), IDC_STATIC_STATUS as i32) }.unwrap_or_default();
    if !h_status.is_invalid() {
        let wide: Vec<u16> = text.encode_utf16().chain(std::iter::once(0)).collect();
        unsafe {
            let _ = SendMessageW(
                h_status,
                WM_SETTEXT,
                Some(WPARAM(0)),
                Some(LPARAM(wide.as_ptr() as isize)),
            );
        }
    }
}

/// 从工作线程更新状态文本（跨线程安全）
///
/// 通过 HWND 原始值重建窗口句柄，用 SetWindowTextW 更新状态。
fn update_status(hwnd_ptr: isize, text: &str) {
    let hwnd = HWND(hwnd_ptr as *mut _);
    let h_status = unsafe { GetDlgItem(Some(hwnd), IDC_STATIC_STATUS as i32) }.unwrap_or_default();
    if !h_status.is_invalid() {
        let wide: Vec<u16> = text.encode_utf16().chain(std::iter::once(0)).collect();
        unsafe {
            let _ = SendMessageW(
                h_status,
                WM_SETTEXT,
                Some(WPARAM(0)),
                Some(LPARAM(wide.as_ptr() as isize)),
            );
        }
    }
}

/// 获取编辑框文本
fn get_edit_text(hwnd: HWND, control_id: u16) -> String {
    let h_edit = unsafe { GetDlgItem(Some(hwnd), control_id as i32) }.unwrap_or_default();
    if h_edit.is_invalid() {
        return String::new();
    }

    let len = unsafe { SendMessageW(h_edit, WM_GETTEXTLENGTH, Some(WPARAM(0)), Some(LPARAM(0))) };
    if len.0 == 0 {
        return String::new();
    }

    let mut buffer = vec![0u16; (len.0 as usize) + 1];
    unsafe {
        let _ = SendMessageW(
            h_edit,
            WM_GETTEXT,
            Some(WPARAM(buffer.len())),
            Some(LPARAM(buffer.as_mut_ptr() as isize)),
        );
    }

    String::from_utf16_lossy(&buffer[..buffer.iter().position(|&c| c == 0).unwrap_or(buffer.len())])
}

/// 获取下拉框选中项文本
fn get_combo_selection(hwnd: HWND, control_id: u16) -> api::VizMode {
    let h_combo = unsafe { GetDlgItem(Some(hwnd), control_id as i32) }.unwrap_or_default();
    if h_combo.is_invalid() {
        return api::VizMode::Auto;
    }

    let sel = unsafe { SendMessageW(h_combo, CB_GETCURSEL, Some(WPARAM(0)), Some(LPARAM(0))) };
    if sel.0 < 0 {
        return api::VizMode::Auto;
    }

    match sel.0 {
        0 => api::VizMode::Auto,
        1 => api::VizMode::Chart,
        2 => api::VizMode::Scientific,
        _ => api::VizMode::Auto,
    }
}

/// 创建并显示主窗口
fn create_main_window() -> Result<HWND> {
    let h_instance = unsafe { GetModuleHandleW(None) }?;
    let class_name = w!("DataVisualWindowClass");

    let wc = WNDCLASSW {
        style: CS_HREDRAW | CS_VREDRAW,
        lpfnWndProc: Some(window_proc),
        hInstance: h_instance.into(),
        lpszClassName: class_name,
        hCursor: unsafe { LoadCursorW(None, IDC_ARROW)? },
        hbrBackground: unsafe { HBRUSH(GetStockObject(WHITE_BRUSH).0) },
        ..Default::default()
    };

    let atom = unsafe { RegisterClassW(&wc) };
    if atom == 0 {
        return Err(windows::core::Error::from(windows::core::HRESULT(-1)));
    }

    let hwnd = unsafe {
        CreateWindowExW(
            WINDOW_EX_STYLE::default(),
            class_name,
            w!("DataVisual - 数据可视化平台"),
            WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            None,
            None,
            Some(HINSTANCE(h_instance.0)),
            None,
        )?
    };

    unsafe { let _ = ShowWindow(hwnd, SW_SHOW); };

    // 启用拖拽文件支持
    unsafe {
        DragAcceptFiles(hwnd, true);
    }

    Ok(hwnd)
}

/// 消息循环
fn run_message_loop() {
    let mut msg = MSG::default();
    while unsafe { GetMessageW(&mut msg, None, 0, 0).into() } {
        unsafe {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    tracing::info!("DataVisual 前端启动中...");

    unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
    }

    let _hwnd = create_main_window()?;

    tracing::info!("窗口已创建，进入消息循环");

    run_message_loop();

    unsafe {
        CoUninitialize();
    }

    tracing::info!("DataVisual 前端已退出");
    Ok(())
}

/// 辅助函数：提取 u32 的低 16 位
fn loword(value: u32) -> u16 {
    (value & 0xFFFF) as u16
}

/// 辅助函数：提取 u32 的高 16 位
fn hiword(value: u32) -> u16 {
    ((value >> 16) & 0xFFFF) as u16
}

// ============================================================
// WebSocket 等待任务完成
// ============================================================

/// 通过 WebSocket 等待任务完成（同步，带重连）
///
/// 连接断开时自动重连（最多 2 次），全部失败才返回 None 触发回退轮询。
fn wait_for_completion_ws(ws_url: &str, hwnd_ptr: isize, task_id: &str) -> Option<api::TaskResponse> {
    use tungstenite::connect;
    use url::Url;

    let url = match Url::parse(ws_url) {
        Ok(u) => u,
        Err(e) => {
            tracing::error!("WebSocket URL 解析失败: {}", e);
            append_log_ptr(hwnd_ptr, &format!("❌ WebSocket URL 解析失败: {}", e));
            return None;
        }
    };

    const MAX_RECONNECT: u32 = 2;

    for attempt in 0..=MAX_RECONNECT {
        if attempt > 0 {
            append_log_ptr(hwnd_ptr, &format!("🔄 重连 WebSocket ({}/{})...", attempt, MAX_RECONNECT));
            std::thread::sleep(std::time::Duration::from_secs(2));
        } else {
            append_log_ptr(hwnd_ptr, "🔗 连接 WebSocket...");
        }

        let (mut socket, _response) = match connect(url.as_str()) {
            Ok(s) => {
                if attempt > 0 {
                    append_log_ptr(hwnd_ptr, "✅ WebSocket 重连成功");
                } else {
                    append_log_ptr(hwnd_ptr, "✅ WebSocket 已连接，等待结果...");
                }
                s
            }
            Err(e) => {
                if attempt < MAX_RECONNECT {
                    append_log_ptr(hwnd_ptr, &format!("⚠️ 连接失败，将重试: {}", e));
                    continue;
                }
                append_log_ptr(hwnd_ptr, &format!("❌ WebSocket 连接失败: {}", e));
                return None;
            }
        };

        use tungstenite::Message;

        loop {
            match socket.read() {
                Ok(Message::Text(text)) => {
                    match serde_json::from_str::<api::TaskCompleteNotification>(&text) {
                        Ok(notif) => {
                            if notif.status == "success" {
                                append_log_ptr(hwnd_ptr, "✅ 后端任务完成");
                                return Some(api::TaskResponse {
                                    task_id: task_id.to_string(),
                                    status: api::TaskStatus::Success,
                                    result: notif.result,
                                    error: None,
                                });
                            } else if notif.status == "failed" || notif.status == "cancelled" {
                                let err = notif.error.unwrap_or_default();
                                append_log_ptr(hwnd_ptr, &format!("❌ {}", err));
                                update_status(hwnd_ptr, &format!("❌ {}", err));
                                return Some(api::TaskResponse {
                                    task_id: task_id.to_string(),
                                    status: api::TaskStatus::Failed,
                                    result: None,
                                    error: Some(err),
                                });
                            } else {
                                append_log_ptr(hwnd_ptr, &format!("📡 收到通知: {}", notif.status));
                            }
                        }
                        Err(e) => {
                            append_log_ptr(hwnd_ptr, &format!("⚠️ 解析通知失败: {}", e));
                        }
                    }
                }
                Ok(Message::Close(_)) => {
                    if attempt < MAX_RECONNECT {
                        append_log_ptr(hwnd_ptr, "⚠️ 连接已关闭，尝试重连...");
                        break;
                    }
                    append_log_ptr(hwnd_ptr, "⚠️ WebSocket 连接已关闭");
                    return None;
                }
                Ok(_) => {}
                Err(e) => {
                    if attempt < MAX_RECONNECT {
                        append_log_ptr(hwnd_ptr, &format!("⚠️ WebSocket 错误，尝试重连: {}", e));
                        break;
                    }
                    tracing::error!("WebSocket 错误: {}", e);
                    append_log_ptr(hwnd_ptr, &format!("❌ WebSocket 错误: {}", e));
                    return None;
                }
            }
        }
    }

    None
}

// ============================================================
// 历史对话功能
// ============================================================

/// 处理"加载历史"按钮点击
fn on_load_history(hwnd: HWND) {
    let client = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref().and_then(|d| d.api_client.clone())
    };

    let client = match client {
        Some(c) => c,
        None => {
            set_status_text(hwnd, "API 客户端未初始化");
            return;
        }
    };

    set_status_text(hwnd, "正在加载历史对话...");
    let hwnd_ptr = hwnd.0 as isize;

    std::thread::spawn(move || {
        let rt = match tokio::runtime::Runtime::new() {
            Ok(rt) => rt,
            Err(e) => {
                tracing::error!("创建 tokio 运行时失败: {}", e);
                return;
            }
        };

        rt.block_on(async {
            match client.list_conversations(50, 0).await {
                Ok(resp) => {
                    let count = resp.conversations.len();
                    {
                        let mut data = APP_DATA.lock().unwrap();
                        if let Some(app_data) = data.as_mut() {
                            app_data.conversations = resp.conversations;
                        }
                    }
                    refresh_history_list_ptr(hwnd_ptr);
                    update_status(hwnd_ptr, &format!("已加载 {} 条历史对话", count));
                }
                Err(e) => {
                    append_log_ptr(hwnd_ptr, &format!("❌ 加载历史失败: {}", e));
                    update_status(hwnd_ptr, &format!("❌ 加载历史失败: {}", e));
                }
            }
        });
    });
}

/// 处理"重提提示词"按钮点击
fn on_resubmit_prompt(hwnd: HWND) {
    let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_HISTORY as i32) }.unwrap_or_default();
    if h_list.is_invalid() {
        return;
    }

    let sel = unsafe { SendMessageW(h_list, LB_GETCURSEL, Some(WPARAM(0)), Some(LPARAM(0))) };
    if sel.0 < 0 {
        set_status_text(hwnd, "请先在历史列表中选择一条对话");
        return;
    }

    let idx = sel.0 as usize;
    let conv_data = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref()
            .and_then(|d| d.conversations.get(idx))
            .map(|c| (c.conversation_id.clone(), c.user_prompt.clone()))
    };

    if let Some((conv_id, prompt)) = conv_data {
        set_edit_text(hwnd, IDC_EDIT_PROMPT, &prompt);
        set_status_text(hwnd, "已填入历史提示词，可修改后重新生成");

        // 同时更新后端记录
        let client = {
            let data = APP_DATA.lock().unwrap();
            data.as_ref().and_then(|d| d.api_client.clone())
        };

        if let Some(client) = client {
            let conv_id_clone = conv_id.clone();
            let prompt_clone = prompt.clone();
            let hwnd_ptr = hwnd.0 as isize;
            std::thread::spawn(move || {
                let rt = match tokio::runtime::Runtime::new() {
                    Ok(rt) => rt,
                    Err(_) => return,
                };
                rt.block_on(async {
                    match client.update_prompt(&conv_id_clone, &prompt_clone).await {
                        Ok(_) => {
                            append_log_ptr(hwnd_ptr, "✅ 提示词已更新到后端");
                        }
                        Err(e) => {
                            append_log_ptr(hwnd_ptr, &format!("⚠️ 更新提示词失败: {}", e));
                        }
                    }
                });
            });
        }
    } else {
        set_status_text(hwnd, "无法获取历史提示词");
    }
}

/// 处理"删除对话"按钮点击
fn on_delete_conversation(hwnd: HWND) {
    let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_HISTORY as i32) }.unwrap_or_default();
    if h_list.is_invalid() {
        return;
    }

    let sel = unsafe { SendMessageW(h_list, LB_GETCURSEL, Some(WPARAM(0)), Some(LPARAM(0))) };
    if sel.0 < 0 {
        set_status_text(hwnd, "请先选择要删除的对话");
        return;
    }

    let idx = sel.0 as usize;
    let conv_id = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref()
            .and_then(|d| d.conversations.get(idx).map(|c| c.conversation_id.clone()))
    };

    let conv_id = match conv_id {
        Some(id) => id,
        None => return,
    };

    let client = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref().and_then(|d| d.api_client.clone())
    };

    let client = match client {
        Some(c) => c,
        None => return,
    };

    set_status_text(hwnd, "正在删除对话...");
    append_log(hwnd, &format!("正在删除对话 {}...", &conv_id[..8]));

    let hwnd_ptr = hwnd.0 as isize;
    std::thread::spawn(move || {
        let rt = match tokio::runtime::Runtime::new() {
            Ok(rt) => rt,
            Err(_) => return,
        };

        rt.block_on(async {
            match client.delete_conversation(&conv_id).await {
                Ok(_) => {
                    append_log_ptr(hwnd_ptr, "✅ 对话已删除");
                    update_status(hwnd_ptr, "对话已删除");

                    // 从本地列表中移除
                    {
                        let mut data = APP_DATA.lock().unwrap();
                        if let Some(app_data) = data.as_mut() {
                            if idx < app_data.conversations.len() {
                                app_data.conversations.remove(idx);
                            }
                        }
                    }
                    refresh_history_list_ptr(hwnd_ptr);
                }
                Err(e) => {
                    append_log_ptr(hwnd_ptr, &format!("❌ 删除失败: {}", e));
                    update_status(hwnd_ptr, &format!("❌ 删除失败: {}", e));
                }
            }
        });
    });
}

/// 处理历史对话列表双击 - 查看对话详情
fn on_view_conversation(hwnd: HWND) {
    let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_HISTORY as i32) }.unwrap_or_default();
    if h_list.is_invalid() {
        return;
    }

    let sel = unsafe { SendMessageW(h_list, LB_GETCURSEL, Some(WPARAM(0)), Some(LPARAM(0))) };
    if sel.0 < 0 {
        return;
    }

    let idx = sel.0 as usize;
    let conv_id = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref()
            .and_then(|d| d.conversations.get(idx).map(|c| c.conversation_id.clone()))
    };

    let conv_id = match conv_id {
        Some(id) => id,
        None => return,
    };

    let client = {
        let data = APP_DATA.lock().unwrap();
        data.as_ref().and_then(|d| d.api_client.clone())
    };

    let client = match client {
        Some(c) => c,
        None => return,
    };

    set_status_text(hwnd, "正在加载对话详情...");
    clear_log(hwnd);
    append_log(hwnd, &format!("加载对话 {} 详情...", &conv_id[..8]));

    let hwnd_ptr = hwnd.0 as isize;
    std::thread::spawn(move || {
        let rt = match tokio::runtime::Runtime::new() {
            Ok(rt) => rt,
            Err(_) => return,
        };

        rt.block_on(async {
            match client.get_conversation(&conv_id).await {
                Ok(conv) => {
                    append_log_ptr(hwnd_ptr, &format!("📝 提示词: {}", conv.user_prompt));
                    append_log_ptr(hwnd_ptr, &format!("📊 状态: {}", conv.status.as_deref().unwrap_or("unknown")));
                    append_log_ptr(hwnd_ptr, &format!("🕐 创建时间: {}", conv.created_at));

                    if let Some(charts) = &conv.charts {
                        if !charts.is_empty() {
                            append_log_ptr(hwnd_ptr, &format!("📈 图表类型: {}", charts.join(", ")));
                        }
                    }

                    if let Some(paths) = &conv.html_file_paths {
                        if !paths.is_empty() {
                            append_log_ptr(hwnd_ptr, "📁 图表文件:");
                            for p in paths {
                                append_log_ptr(hwnd_ptr, &format!("  - {}", p));
                            }
                        }
                    }

                    if let Some(error) = &conv.error {
                        append_log_ptr(hwnd_ptr, &format!("❌ 错误: {}", error));
                    }

                    if let Some(logs) = &conv.agent_logs {
                        if !logs.is_empty() {
                            append_log_ptr(hwnd_ptr, "── 执行日志 ──");
                            for log_line in logs {
                                append_log_ptr(hwnd_ptr, log_line);
                            }
                            append_log_ptr(hwnd_ptr, "── 日志结束 ──");
                        }
                    }

                    update_status(hwnd_ptr, "对话详情已加载");
                }
                Err(e) => {
                    append_log_ptr(hwnd_ptr, &format!("❌ 加载失败: {}", e));
                    update_status(hwnd_ptr, &format!("❌ 加载失败: {}", e));
                }
            }
        });
    });
}

/// 刷新历史对话列表框
fn refresh_history_list(hwnd: HWND) {
    let h_list = unsafe { GetDlgItem(Some(hwnd), IDC_LIST_HISTORY as i32) }.unwrap_or_default();
    if h_list.is_invalid() {
        return;
    }

    unsafe {
        let _ = SendMessageW(h_list, LB_RESETCONTENT, Some(WPARAM(0)), Some(LPARAM(0)));
    }

    let data = APP_DATA.lock().unwrap();
    if let Some(app_data) = data.as_ref() {
        for conv in &app_data.conversations {
            let status = conv.status.as_deref().unwrap_or("?");
            let display = format!("[{}] {}", status, conv.user_prompt);
            let wide: Vec<u16> = display.encode_utf16().chain(std::iter::once(0)).collect();
            unsafe {
                let _ = SendMessageW(
                    h_list,
                    LB_ADDSTRING,
                    Some(WPARAM(0)),
                    Some(LPARAM(wide.as_ptr() as isize)),
                );
            }
        }
    }
}

/// 从工作线程刷新历史对话列表框
fn refresh_history_list_ptr(hwnd_ptr: isize) {
    let hwnd = HWND(hwnd_ptr as *mut _);
    refresh_history_list(hwnd);
}

/// 设置编辑框文本
fn set_edit_text(hwnd: HWND, control_id: u16, text: &str) {
    let h_edit = unsafe { GetDlgItem(Some(hwnd), control_id as i32) }.unwrap_or_default();
    if !h_edit.is_invalid() {
        let wide: Vec<u16> = text.encode_utf16().chain(std::iter::once(0)).collect();
        unsafe {
            let _ = SendMessageW(
                h_edit,
                WM_SETTEXT,
                Some(WPARAM(0)),
                Some(LPARAM(wide.as_ptr() as isize)),
            );
        }
    }
}
