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

// ===== 轻量工具提示：给图标按钮和需要解释的控件补上悬浮说明 =====
// 原生 title 的提示出现慢、样式不可控，而且在按钮上会和 aria-label 重复。
// 这里统一接管 [data-tip] / [title]：鼠标悬浮 320ms 后显示，键盘聚焦立即显示；
// title 会迁移到 data-tip，避免和浏览器原生提示同时出现。
const UI_TIP_DELAY = 320;
const UI_TIP_GAP = 8;
let _tipEl = null;
let _tipTarget = null;
let _tipTimer = null;

function _ensureTipEl() {
  if (_tipEl) return _tipEl;
  _tipEl = document.createElement('div');
  _tipEl.className = 'ui-tooltip';
  _tipEl.id = 'uiTooltip';
  _tipEl.setAttribute('role', 'tooltip');
  document.body.appendChild(_tipEl);
  return _tipEl;
}

function _tipText(el) {
  if (!el) return '';
  let text = el.getAttribute('data-tip');
  if (!text) {
    const title = el.getAttribute('title');
    if (title) {
      text = title;
      el.setAttribute('data-tip', title);
      el.removeAttribute('title');
    }
  }
  return String(text || '').trim();
}

function _restoreTipDescribedBy(el) {
  if (!el) return;
  if (el.hasAttribute('data-tip-describedby')) {
    const old = el.getAttribute('data-tip-describedby');
    if (old) el.setAttribute('aria-describedby', old);
    else el.removeAttribute('aria-describedby');
    el.removeAttribute('data-tip-describedby');
  }
}

function _placeTip(target, tip) {
  const rect = target.getBoundingClientRect();
  if (!rect.width && !rect.height) return false;

  // 先设置文本再测量；tooltip 仍处于 visibility:hidden，不会闪烁。
  tip.style.visibility = 'hidden';
  tip.classList.add('show');
  const size = tip.getBoundingClientRect();
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const margin = 8;
  const canTop = rect.top >= size.height + UI_TIP_GAP + margin;
  const canBottom = vh - rect.bottom >= size.height + UI_TIP_GAP + margin;
  const preferred = target.getAttribute('data-tip-placement');
  const placement = preferred || (canTop || !canBottom ? 'top' : 'bottom');

  let top = placement === 'top'
    ? rect.top - size.height - UI_TIP_GAP
    : rect.bottom + UI_TIP_GAP;
  let left = rect.left + rect.width / 2 - size.width / 2;
  left = Math.max(margin, Math.min(left, vw - size.width - margin));
  top = Math.max(margin, Math.min(top, vh - size.height - margin));

  tip.style.left = Math.round(left) + 'px';
  tip.style.top = Math.round(top) + 'px';
  tip.dataset.placement = placement;
  // 箭头始终指向目标中心；靠近屏幕边缘时夹在圆角范围内。
  const arrow = Math.max(12, Math.min(size.width - 12, rect.left + rect.width / 2 - left));
  tip.style.setProperty('--tip-arrow', arrow + 'px');
  tip.style.visibility = '';
  return true;
}

function showUiTooltip(target, immediate) {
  const text = _tipText(target);
  if (!text) return;
  if (_tipTarget === target && _tipEl && _tipEl.classList.contains('show')) return;

  clearTimeout(_tipTimer);
  if (_tipTarget && _tipTarget !== target) hideUiTooltip();
  // 立即记下目标：这样 pointerout 能在 320ms 延迟到期前取消待显示的提示。
  _tipTarget = target;

  _tipTimer = setTimeout(() => {
    if (_tipTarget !== target || !target.isConnected) return;
    const tip = _ensureTipEl();
    tip.textContent = text;

    const current = target.getAttribute('aria-describedby') || '';
    if (current.split(/\s+/).indexOf('uiTooltip') < 0) {
      target.setAttribute('data-tip-describedby', current);
      target.setAttribute('aria-describedby', (current + ' uiTooltip').trim());
    }
    if (!_placeTip(target, tip)) hideUiTooltip();
  }, immediate ? 0 : UI_TIP_DELAY);
}

function hideUiTooltip() {
  clearTimeout(_tipTimer);
  _tipTimer = null;
  if (_tipTarget) _restoreTipDescribedBy(_tipTarget);
  _tipTarget = null;
  if (_tipEl) _tipEl.classList.remove('show');
}

function _tipTargetFromEvent(e) {
  const node = e && e.target;
  if (!node || node.nodeType !== 1 || !node.closest) return null;
  return node.closest('[data-tip], [title]');
}

(function initUiTooltip() {
  document.addEventListener('pointerover', e => {
    if (e.pointerType === 'touch') return;
    const target = _tipTargetFromEvent(e);
    if (!target || target === _tipTarget) return;
    showUiTooltip(target, false);
  });

  document.addEventListener('pointerout', e => {
    const target = _tipTargetFromEvent(e);
    if (!target) return;
    const related = e.relatedTarget;
    if (related && target.contains(related)) return;
    if (_tipTarget === target) hideUiTooltip();
  });

  document.addEventListener('focusin', e => {
    const target = _tipTargetFromEvent(e);
    if (!target || target === _tipTarget) return;
    // 鼠标点击也会触发 focus，只在键盘聚焦（:focus-visible）时显示。
    let visible = true;
    try { visible = target.matches(':focus-visible'); } catch (err) { visible = true; }
    if (visible) showUiTooltip(target, true);
  });

  document.addEventListener('focusout', e => {
    const target = _tipTargetFromEvent(e);
    if (target && _tipTarget === target) hideUiTooltip();
  });

  document.addEventListener('pointerdown', hideUiTooltip, true);
  document.addEventListener('click', hideUiTooltip, true);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') hideUiTooltip();
  });
  window.addEventListener('scroll', hideUiTooltip, true);
  window.addEventListener('resize', hideUiTooltip);
})();

// 键盘可达：建议卡片是 div，补上 Enter / Space 激活（与点击等价）
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const card = e.target.closest ? e.target.closest('.suggestion-card[role="button"]') : null;
  if (card && e.target === card) {
    e.preventDefault();
    card.click();
  }
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
