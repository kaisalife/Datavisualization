// ===== 全局状态与桥接通信 =====
const BRIDGE_PORT = __BRIDGE_PORT__;
const BRIDGE_URL = 'http://127.0.0.1:' + BRIDGE_PORT + '/api';

const state = {
  mode: 'chat',
  vizMode: 'auto',
  files: [],
  fileList: [],
  projectName: null,
  conversations: [],
  isGenerating: false,
  selectedDb: null,
  dbConfigs: [],
  sidebarTab: 'conversations',
  activeTaskEl: null,
  activeLogs: [],
  lastChartData: null,
  backendUrl: '',
};

// JS -> Rust 桥接
function sendToRust(action, data) {
  fetch(BRIDGE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: action, data: data || {} })
  }).catch(err => {
    console.error('[Bridge] 发送失败:', err);
    if (window.app && window.app.showToast) window.app.showToast('操作失败，请重试', 'error');
  });
}
