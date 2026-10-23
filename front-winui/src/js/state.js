// ===== 全局状态与桥接通信 =====
const BRIDGE_PORT = __BRIDGE_PORT__;
const BRIDGE_URL = 'http://127.0.0.1:' + BRIDGE_PORT + '/api';

const state = {
  mode: 'chat',
  vizMode: 'auto',
  files: [],
  lastFiles: [],
  fileList: [],
  projectName: null,
  conversations: [],
  isGenerating: false,
  multiTable: false,
  selectedDb: null,
  dbConfigs: [],
  sidebarTab: 'conversations',
  activeTaskEl: null,
  activeLogs: [],
  lastChartData: null,
  backendUrl: '',
  config: null,
  conversationId: null,   // 当前对话 ID（资产面板按它加载）
  assets: [],             // 当前对话图表资产 [{chart_id,title,version,...}]
  assetsLoading: false,
  optimizeTarget: null,   // 二次优化目标 {chartId, title}
  followTail: true,       // 聊天区是否跟随最新内容（用户上滑阅读时为 false）
  unread: 0,              // 未读新内容条数（上滑时累积，用于“回到最新”角标）
  autoOpenLogs: true,     // 本任务是否自动展开 Agent 日志（历史恢复 / 已完成的默认收起）
};

// 前端渲染上限：避免单条消息/日志把 DOM 撑爆（超出的最早条目被丢弃，
// 完整日志仍保留在 state.activeLogs 供“复制日志”使用）。
const LOG_DOM_MAX = 500;      // 日志面板最多保留的 DOM 行数
const LOG_BUFFER_MAX = 3000;  // 复制日志用的内存缓冲上限
const TRACE_DOM_MAX = 400;    // 执行轨迹最多保留的节点数
const TOAST_MAX = 4;          // 同屏最多 toast 数
const AUTO_SCROLL_THRESHOLD = 80; // 距底部多少像素内算“跟随”

// JS -> Rust 桥接
// 桥接服务器只做入队后立即返回，正常 <50ms；加 10s 超时与失败提示，
// 避免桥接线程卡住时前端静默无响应（也不做自动重试，防止重复提交任务）。
let _bridgeErrorAt = 0;
function sendToRust(action, data) {
  const controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), 10000) : null;
  fetch(BRIDGE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: action, data: data || {} }),
    signal: controller ? controller.signal : undefined,
  }).then(resp => {
    if (timer) clearTimeout(timer);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
  }).catch(err => {
    if (timer) clearTimeout(timer);
    console.error('[Bridge] 发送失败:', action, err);
    const now = Date.now();
    if (now - _bridgeErrorAt > 5000 && window.app && window.app.showToast) {
      _bridgeErrorAt = now;
      window.app.showToast('本地服务通信失败，请重启应用后重试', 'error');
    }
  });
}
