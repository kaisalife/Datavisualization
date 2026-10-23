// ===== 工具函数 =====

// ---- 聊天滚动：只在用户本来就在底部附近时跟随，避免打断向上翻阅 ----
let _scrollScheduled = false;

function isNearBottom(el, threshold) {
  if (!el) return true;
  const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
  return gap <= (threshold == null ? AUTO_SCROLL_THRESHOLD : threshold);
}

// force=true 时无条件滚到底（用户自己发送消息、点击“回到最新”）
function scrollToBottom(opts) {
  const force = !!(opts && opts.force);
  const el = document.getElementById('chatMessages');
  if (!el) return;
  if (force) {
    state.followTail = true;
    state.unread = 0;
    updateScrollButton();
  } else if (!state.followTail) {
    state.unread++;
    updateScrollButton();
    return;
  }
  if (_scrollScheduled) return;
  _scrollScheduled = true;
  requestAnimationFrame(() => {
    _scrollScheduled = false;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function updateScrollButton() {
  const btn = document.getElementById('scrollBottomBtn');
  if (!btn) return;
  const show = !state.followTail;
  btn.classList.toggle('show', show);
  const badge = btn.querySelector('.scroll-bottom-count');
  if (badge) {
    badge.textContent = state.unread > 99 ? '99+' : String(state.unread);
    badge.style.display = state.unread > 0 ? 'inline-flex' : 'none';
  }
}

(function initChatScroll() {
  const el = document.getElementById('chatMessages');
  if (!el) return;
  el.addEventListener('scroll', () => {
    state.followTail = isNearBottom(el);
    if (state.followTail) state.unread = 0;
    updateScrollButton();
  }, { passive: true });
})();

// “回到最新”按钮贴在输入区上方：输入区高度会随文件 chip / 多行输入变化，
// 用 ResizeObserver 同步偏移，避免按钮压住输入框。
(function initScrollButtonOffset() {
  const area = document.querySelector('.chat-input-area');
  const btn = document.getElementById('scrollBottomBtn');
  if (!area || !btn) return;
  const sync = () => { btn.style.bottom = (area.offsetHeight + 12) + 'px'; };
  sync();
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(sync).observe(area);
})();

// 启动后把焦点放到输入框，用户打开应用即可直接输入
function focusPrompt() {
  const input = document.getElementById('prompt-input');
  if (input) input.focus();
}

window.addEventListener('load', () => setTimeout(focusPrompt, 80));

// ---- 输入防抖（搜索框逐字过滤不必每键都重建整个列表）----
function debounce(fn, wait) {
  let timer = null;
  return function () {
    const args = arguments;
    const ctx = this;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn.apply(ctx, args);
    }, wait == null ? 120 : wait);
  };
}

function nowStr() {
  const d = new Date();
  return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0') + ':' + d.getSeconds().toString().padStart(2,'0');
}

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escAttr(s) {
  if (s == null) return '';
  return String(s).replace(/\\/g,'\\\\').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ---- 剪贴板：优先异步 API，不可用时退回隐藏 textarea + execCommand ----
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-1000px';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand && document.execCommand('copy');
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error('copy command rejected'));
    } catch (e) {
      reject(e);
    }
  });
}

// ---- 全局异常兜底：不再静默失败，控制台必记、Toast 限流 ----
let _lastErrorAt = 0;
function reportFrontendError(kind, detail) {
  console.error('[Frontend]', kind, detail);
  const now = Date.now();
  if (now - _lastErrorAt < 5000) return;
  _lastErrorAt = now;
  if (window.app && window.app.showToast) {
    window.app.showToast('界面出现异常，已记录到控制台', 'error');
  }
}

window.addEventListener('error', e => reportFrontendError('脚本错误', e && e.message));
window.addEventListener('unhandledrejection', e => {
  const reason = e && e.reason;
  reportFrontendError('异步错误', (reason && (reason.message || reason)) || 'unknown');
});

// ---- Esc 关闭最上层浮层 ----
function _overlayVisible(id) {
  const el = document.getElementById(id);
  return !!(el && el.classList.contains('show'));
}

function closeTopmostOverlay() {
  // 全屏查看器在最上层；其余浮层按打开顺序的常见情况排列
  if (_overlayVisible('skillManagerModal') && typeof closeSkillManager === 'function') return closeSkillManager(), true;
  if (_overlayVisible('chartViewer') && typeof closeChartViewer === 'function') return closeChartViewer(), true;
  if (_overlayVisible('dataPreviewModal') && typeof closeDataPreview === 'function') return closeDataPreview(), true;
  if (_overlayVisible('settingsModal')) return sendToRust('toggleSettings', {}), true;
  if (_overlayVisible('dbSelectorModal')) return document.getElementById('dbSelectorModal').classList.remove('show'), true;
  if (_overlayVisible('apiConfigModal')) return document.getElementById('apiConfigModal').classList.remove('show'), true;
  if (typeof closeCleanupModal === 'function') {
    const el = document.getElementById('cleanupModal');
    if (el && el.style.display !== 'none') return closeCleanupModal(), true;
  }
  return false;
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && closeTopmostOverlay()) e.preventDefault();
});

// ===== 拖拽上传 =====
const inputBox = document.getElementById('chatInputBox');
if (inputBox) {
  inputBox.addEventListener('dragover', e => { e.preventDefault(); inputBox.classList.add('dragover'); });
  inputBox.addEventListener('dragleave', () => inputBox.classList.remove('dragover'));
  inputBox.addEventListener('drop', e => {
    e.preventDefault(); inputBox.classList.remove('dragover');
    window.app.showToast('请使用附件按钮选择文件', 'info');
  });
}

// ===== 初始化 =====
sendToRust('loadHistory', {});
