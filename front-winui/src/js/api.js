// ===== window.app 命名空间：Rust -> JS 回调 API =====
// Trace WebSocket 监控已拆分到 trace.js
window.app = {
  addMessage(role, content) {
    hideWelcome();
    try {
      const parsed = JSON.parse(content);
      if (parsed.type === 'charts' && parsed.items) {
        appendAiChartsMessage(parsed);
        scrollToBottom();
        return;
      }
      if (parsed.type === 'code' && parsed.code) {
        appendMessage(role, content, 'code');
        scrollToBottom();
        return;
      }
    } catch(e) { /* 普通文本 */ }
    appendMessage(role, content, 'text');
    scrollToBottom();
  },

  clearMessages() {
    document.getElementById('chatInner').innerHTML = '';
    showWelcome();
    state.activeTaskEl = null;
    state.activeLogs = [];
  },

  startTaskMessage(text) {
    hideWelcome();
    const el = buildAiTaskMessage(text);
    document.getElementById('chatInner').appendChild(el);
    state.activeTaskEl = el;
    state.activeLogs = [];
    scrollToBottom();
  },

  appendLog(text) {
    state.activeLogs.push(text);
    // 自动检测 task_id 并订阅 trace WebSocket
    const match = String(text).match(/任务已提交[:\s]*([a-f0-9]+)/i);
    if (match && match[1]) {
      window.app.subscribeTrace(match[1]);
    }
    const body = state.activeTaskEl ? state.activeTaskEl.querySelector('.agent-log-body') : null;
    if (body) {
      body.classList.add('show');
      const toggle = state.activeTaskEl.querySelector('.agent-log-toggle');
      if (toggle) toggle.classList.add('expanded');
      const div = document.createElement('div');
      div.className = 'log-entry';
      div.innerHTML = '<span class="log-time">' + nowStr() + '</span><span class="log-msg"></span>';
      div.querySelector('.log-msg').textContent = text;
      body.appendChild(div);
      body.scrollTop = body.scrollHeight;
    }
    scrollToBottom();
  },

  setProgress(percent, text) {
    if (state.activeTaskEl) {
      const fill = state.activeTaskEl.querySelector('.progress-fill');
      const label = state.activeTaskEl.querySelector('.progress-label');
      if (fill) fill.style.width = percent + '%';
      if (label && text) label.textContent = text;
    }
    if (text) window.app.setStatus(text);
  },

  completeTask(chartsJsonStr) {
    let parsed;
    try { parsed = JSON.parse(chartsJsonStr); } catch(e) { parsed = { items: [] }; }
    window.app.stopStageTimer();
    state.lastChartData = parsed;
    if (state.activeTaskEl) {
      const container = state.activeTaskEl.querySelector('.task-charts');
      if (container) renderChartGrid(container, parsed.items || []);
      const summary = state.activeTaskEl.querySelector('.task-summary');
      if (summary) {
        const total = (parsed.items || []).length;
        summary.textContent = '任务完成，共生成 ' + total + ' 个图表。';
      }
      const typing = state.activeTaskEl.querySelector('.typing');
      if (typing) typing.style.display = 'none';
    }
    scrollToBottom();
  },

  failTask(err) {
    window.app.stopStageTimer();
    if (state.activeTaskEl) {
      const typing = state.activeTaskEl.querySelector('.typing');
      if (typing) typing.style.display = 'none';
      const summary = state.activeTaskEl.querySelector('.task-summary');
      if (summary) {
        summary.textContent = err;
        summary.style.color = 'var(--error)';
      }
    } else {
      appendMessage('assistant', err, 'text');
    }
    scrollToBottom();
  },

  setGenerating(generating) {
    state.isGenerating = generating;
    const sendBtn = document.getElementById('send-btn');
    const cancelBtn = document.getElementById('cancel-btn');
    if (generating) {
      sendBtn.style.display = 'none';
      cancelBtn.style.display = 'flex';
    } else {
      sendBtn.style.display = 'flex';
      cancelBtn.style.display = 'none';
    }
  },

  clearInput() {
    const input = document.getElementById('prompt-input');
    input.value = '';
    input.style.height = 'auto';
  },

  setConversationList(jsonStr, total) {
    try { state.conversations = JSON.parse(jsonStr); } catch(e) { state.conversations = []; }
    state.total = total || 0;
    if (state.sidebarTab === 'conversations') renderConversations();
    checkCleanupReminder();
  },

  setFileList(jsonStr) {
    try { state.fileList = JSON.parse(jsonStr); } catch(e) { state.fileList = []; }
    if (state.projectName) {
      document.getElementById('projectInfo').style.display = 'flex';
      document.getElementById('projName').textContent = state.projectName;
      document.getElementById('fileSearchBox').style.display = 'block';
    }
    if (state.sidebarTab === 'files') renderFileTree();
  },

  setFileChips(jsonStr) {
    try { state.files = JSON.parse(jsonStr); } catch(e) { state.files = []; }
    renderFileChips();
  },

  setMode(mode) {
    state.mode = mode;
    const tabChat = document.getElementById('tab-chat');
    const tabCode = document.getElementById('tab-code');
    const input = document.getElementById('prompt-input');
    if (mode === 'code') {
      tabChat.classList.remove('active');
      tabCode.classList.add('active');
      input.placeholder = '输入代码补全需求，按 Enter 发送...';
    } else {
      tabChat.classList.add('active');
      tabCode.classList.remove('active');
      input.placeholder = '描述你想要的图表，按 Enter 发送...';
    }
  },

  showSettings(jsonStr) {
    let cfg;
    try { cfg = JSON.parse(jsonStr); } catch(e) { cfg = {}; }
    renderSettings(cfg);
    document.getElementById('settingsModal').classList.add('show');
  },

  hideSettings() {
    document.getElementById('settingsModal').classList.remove('show');
  },

  showToast(message, type) {
    const c = document.getElementById('toastContainer');
    const d = document.createElement('div');
    d.className = 'toast ' + (type || 'info');
    d.textContent = message;
    c.appendChild(d);
    setTimeout(() => { d.style.opacity = '0'; d.style.transition = 'opacity 0.3s'; setTimeout(() => d.remove(), 300); }, 3000);
  },

  setStatus(text) {
    document.getElementById('status-bar').textContent = text;
  },

  setDbConfigs(jsonStr) {
    try { state.dbConfigs = JSON.parse(jsonStr); } catch(e) { state.dbConfigs = []; }
  },

  setSelectedDb(name) {
    state.selectedDb = name;
  },

  setBackend(url) {
    state.backendUrl = url || '';
  },

  setModelConfigs(jsonStr) {
    try { state.modelConfigs = JSON.parse(jsonStr); } catch(e) { state.modelConfigs = []; }
    if (typeof renderModelList === 'function') renderModelList();
  },

  openChart(url) {
    window.open(url, '_blank');
  },

  completeCodeTask(codeJsonStr) {
    let parsed;
    try { parsed = JSON.parse(codeJsonStr); } catch(e) { parsed = { code: codeJsonStr }; }
    if (state.activeTaskEl) {
      const typing = state.activeTaskEl.querySelector('.typing');
      if (typing) typing.style.display = 'none';
      const progress = state.activeTaskEl.querySelector('.msg-progress');
      if (progress) progress.style.display = 'none';
      const bubble = state.activeTaskEl.querySelector('.msg-bubble');
      if (bubble && parsed.code) {
        const pre = document.createElement('pre');
        const code = document.createElement('code');
        code.textContent = parsed.code;
        pre.appendChild(code);
        bubble.innerHTML = '';
        bubble.appendChild(pre);
      }
      const summary = state.activeTaskEl.querySelector('.task-summary');
      if (summary) summary.textContent = '代码补全完成。';
    } else {
      window.app.addMessage('assistant', codeJsonStr);
    }
    scrollToBottom();
  },

  cancelTask() {
    if (state.activeTaskEl) {
      const typing = state.activeTaskEl.querySelector('.typing');
      if (typing) typing.style.display = 'none';
      const progress = state.activeTaskEl.querySelector('.msg-progress');
      if (progress) progress.style.display = 'none';
      const summary = state.activeTaskEl.querySelector('.task-summary');
      if (summary) {
        summary.textContent = '任务已取消';
        summary.style.color = 'var(--text-secondary)';
      }
    }
    scrollToBottom();
  },

  /// 还原历史对话（从后端数据库加载后重建聊天界面）
  restoreConversation(detailJsonStr) {
    let d;
    try { d = JSON.parse(detailJsonStr); } catch(e) { return; }

    // 1. 清空消息
    document.getElementById('chatInner').innerHTML = '';
    state.activeTaskEl = null;
    state.activeLogs = [];
    hideWelcome();

    // 2. 渲染用户消息（含文件标签）
    if (d.user_prompt) {
      const msg = document.createElement('div');
      msg.className = 'msg user';
      const avatar = document.createElement('div');
      avatar.className = 'msg-avatar user';
      avatar.textContent = 'K';
      const content = document.createElement('div');
      content.className = 'msg-content';
      content.innerHTML = '<div class="msg-name">你</div>';
      const bubble = document.createElement('div');
      bubble.className = 'msg-bubble';
      bubble.textContent = d.user_prompt;
      content.appendChild(bubble);
      // 文件标签
      if (d.file_paths && d.file_paths.length > 0) {
        const chipsDiv = document.createElement('div');
        chipsDiv.className = 'msg-files';
        chipsDiv.style.marginTop = '6px';
        d.file_paths.forEach(fp => {
          const chip = document.createElement('span');
          chip.className = 'file-chip';
          const fname = String(fp).split(/[\\/]/).pop();
          chip.textContent = '📄 ' + fname;
          chipsDiv.appendChild(chip);
        });
        content.appendChild(chipsDiv);
      }
      msg.appendChild(avatar);
      msg.appendChild(content);
      document.getElementById('chatInner').appendChild(msg);
    }

    // 3. 创建任务消息
    const status = d.status || 'success';
    let taskText = '正在为你生成图表，首先对数据进行质量检查和清洗，然后基于数据特征生成可视化方案。';
    if (status === 'failed') taskText = '任务执行失败。';
    else if (status === 'running') taskText = '任务执行中...';
    else if (status === 'pending') taskText = '任务等待中...';
    window.app.startTaskMessage(taskText);

    // 4. 还原 Agent 日志
    if (d.agent_logs && d.agent_logs.length > 0) {
      d.agent_logs.forEach(log => window.app.appendLog(log));
    }

    // 5. 根据状态完成或失败
    if (status === 'success') {
      const items = d.chart_items || [];
      window.app.completeTask(JSON.stringify({ type: 'charts', items: items }));
    } else if (status === 'failed') {
      window.app.failTask(d.error || '任务失败');
    }

    // 隐藏打字动画和进度条（历史对话不需要）
    if (state.activeTaskEl) {
      const typing = state.activeTaskEl.querySelector('.typing');
      if (typing) typing.style.display = 'none';
      const progress = state.activeTaskEl.querySelector('.msg-progress');
      if (progress) progress.style.display = 'none';
    }

    scrollToBottom();
  },
};
