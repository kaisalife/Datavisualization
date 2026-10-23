// ===== 输入框与发送逻辑 =====
function useSuggestion(type) {
  const prompts = { csv: '分析这份销售数据，按季度生成趋势折线图', excel: '对比多个 Excel 表格的产品类别表现', db: '连接数据库，分析用户注册趋势', pdf: '从 PDF 报表中提取表格数据并可视化' };
  const input = document.getElementById('prompt-input');
  input.value = prompts[type] || '';
  autoResize(input);
  input.focus();
}

function selectMode(el, mode) {
  document.querySelectorAll('.mode-chip[data-mode]').forEach(c => {
    c.classList.remove('active');
    c.setAttribute('aria-pressed', 'false');
  });
  el.classList.add('active');
  el.setAttribute('aria-pressed', 'true');
  state.vizMode = mode;
}

function toggleMultiTable() {
  state.multiTable = !state.multiTable;
  const chip = document.getElementById('multi-table-chip');
  if (chip) {
    chip.classList.toggle('active', state.multiTable);
    chip.setAttribute('aria-pressed', state.multiTable ? 'true' : 'false');
  }
}

// ===== 二次优化：选中某张已生成的图，输入区进入优化模式 =====
function setOptimizeTarget(chartId, title) {
  state.optimizeTarget = { chartId: chartId, title: title || chartId };
  renderOptimizeChip();
  const input = document.getElementById('prompt-input');
  if (input) {
    input.value = '优化“' + (title || chartId) + '”：';
    if (typeof autoResize === 'function') autoResize(input);
    input.focus();
    if (input.scrollIntoView) input.scrollIntoView({ block: 'nearest' });
  }
}

function clearOptimizeTarget() {
  state.optimizeTarget = null;
  renderOptimizeChip();
}

function renderOptimizeChip() {
  const chip = document.getElementById('optimizeChip');
  const label = document.getElementById('optimizeChipLabel');
  if (!chip || !label) return;
  if (state.optimizeTarget) {
    label.textContent = '优化：' + state.optimizeTarget.title + '（只改图形，不重跑数据）';
    chip.style.display = 'flex';
  } else {
    chip.style.display = 'none';
    label.textContent = '';
  }
}

function sendPrompt() {
  const input = document.getElementById('prompt-input');
  const prompt = input.value.trim();
  if (!prompt || state.isGenerating) return;
  const optimizeTarget = state.optimizeTarget;
  if (optimizeTarget) clearOptimizeTarget();
  const filesToSend = state.files.filter(f => typeof f === 'string');
  // 保留本次输入的数据源，供“补充说明并重试”恢复，不必重新选文件
  state.lastFiles = state.files.map(f => (typeof f === 'object' ? { ...f } : f));
  // 渲染用户消息（含文件标签）
  hideWelcome();
  const userMsg = document.createElement('div');
  userMsg.className = 'msg user';
  let fileHtml = '';
  if (state.files.length > 0) {
    fileHtml = '<div class="msg-files">' + state.files.map(f => {
      const isObj = typeof f === 'object';
      const name = isObj ? f.name : (f.split(/[\\/]/).pop() || f);
      const icon = isObj && f.isDb ? '🗄️' : '📄';
      return '<div class="msg-file">' + icon + ' ' + escHtml(name) + '</div>';
    }).join('') + '</div>';
  }
  const content = document.createElement('div');
  content.className = 'msg-content';
  const bubbleText = optimizeTarget
    ? '🛠 优化《' + optimizeTarget.title + '》：' + prompt
    : prompt;
  content.innerHTML = '<div class="msg-name">你</div><div class="msg-bubble"></div>' + fileHtml;
  content.querySelector('.msg-bubble').textContent = bubbleText;
  userMsg.innerHTML = '<div class="msg-avatar user">K</div>';
  userMsg.appendChild(content);
  document.getElementById('chatInner').appendChild(userMsg);
  // 清空输入和文件
  input.value = '';
  input.style.height = 'auto';
  state.files = [];
  renderFileChips();
  // 发送到 Rust
  if (optimizeTarget) {
    sendToRust('optimizeChart', { chartId: optimizeTarget.chartId, prompt: prompt });
  } else if (state.mode === 'code') {
    sendToRust('completeCode', { prompt: prompt, files: filesToSend });
  } else {
    sendToRust('sendPrompt', { prompt: prompt, files: filesToSend, vizMode: state.vizMode, multiTable: state.multiTable, dbConfig: state.selectedDb, apiConfig: state.apiConfig || null, config: state.config || null });
  }
  scrollToBottom({ force: true });
}

function cancelTask() { sendToRust('cancelTask', {}); }

function newChat() {
  state.files = [];
  state.lastFiles = [];
  state.selectedDb = null;
  state.apiConfig = null;
  state.optimizeTarget = null;
  renderOptimizeChip();
  renderFileChips();
  sendToRust('newChat', {});
}

function handleInputKey(e) {
  // 中文输入法组词中按 Enter 是“上屏”，不能当成发送
  if (e.isComposing || e.keyCode === 229) return;
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendPrompt(); }
}

// 自动撑高输入框：逐字触发时合并到一帧内完成，避免每按一键都强制同步布局
const _resizeTargets = new Set();
let _resizeScheduled = false;

function autoResize(el) {
  if (!el) return;
  _resizeTargets.add(el);
  if (_resizeScheduled) return;
  _resizeScheduled = true;
  requestAnimationFrame(() => {
    _resizeScheduled = false;
    _resizeTargets.forEach(target => {
      target.style.height = 'auto';
      target.style.height = Math.min(target.scrollHeight, 120) + 'px';
    });
    _resizeTargets.clear();
  });
}
