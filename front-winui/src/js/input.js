// ===== 输入框与发送逻辑 =====
function useSuggestion(type) {
  const prompts = { csv: '分析这份销售数据，按季度生成趋势折线图', excel: '对比多个 Excel 表格的产品类别表现', db: '连接数据库，分析用户注册趋势', pdf: '从 PDF 报表中提取表格数据并可视化' };
  const input = document.getElementById('prompt-input');
  input.value = prompts[type] || '';
  autoResize(input);
  input.focus();
}

function selectMode(el, mode) {
  document.querySelectorAll('.mode-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  state.vizMode = mode;
}

function sendPrompt() {
  const input = document.getElementById('prompt-input');
  const prompt = input.value.trim();
  if (!prompt || state.isGenerating) return;
  const filesToSend = state.files.filter(f => typeof f === 'string');
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
  content.innerHTML = '<div class="msg-name">你</div><div class="msg-bubble"></div>' + fileHtml;
  content.querySelector('.msg-bubble').textContent = prompt;
  userMsg.innerHTML = '<div class="msg-avatar user">K</div>';
  userMsg.appendChild(content);
  document.getElementById('chatInner').appendChild(userMsg);
  // 清空输入和文件
  input.value = '';
  input.style.height = 'auto';
  state.files = [];
  renderFileChips();
  // 发送到 Rust
  if (state.mode === 'code') {
    sendToRust('completeCode', { prompt: prompt, files: filesToSend });
  } else {
    sendToRust('sendPrompt', { prompt: prompt, files: filesToSend, vizMode: state.vizMode, dbConfig: state.selectedDb, apiConfig: state.apiConfig || null, config: state.config || null });
  }
  scrollToBottom();
}

function cancelTask() { sendToRust('cancelTask', {}); }

function newChat() {
  state.files = [];
  state.selectedDb = null;
  state.apiConfig = null;
  renderFileChips();
  sendToRust('newChat', {});
}

function handleInputKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendPrompt(); }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}
