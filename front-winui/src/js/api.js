// ===== window.app 命名空间：Rust -> JS 回调 API =====
// Trace WebSocket 监控已拆分到 trace.js

// 日志渲染批处理：后端可能连续推几十条日志，逐条插入会反复触发重排，
// 这里合并到一次 requestAnimationFrame 内批量插入片段。
let _pendingLogs = [];
let _logFlushScheduled = false;

function _flushLogs() {
  _logFlushScheduled = false;
  if (_pendingLogs.length === 0) return;
  const pending = _pendingLogs;
  _pendingLogs = [];
  const body = state.activeTaskEl ? state.activeTaskEl.querySelector('.agent-log-body') : null;
  if (!body) return;
  const autoOpen = state.autoOpenLogs !== false;
  if (autoOpen) {
    body.classList.add('show');
    const toggle = state.activeTaskEl.querySelector('.agent-log-toggle');
    if (toggle) {
      toggle.classList.add('expanded');
      toggle.setAttribute('aria-expanded', 'true');
    }
  }

  const frag = document.createDocumentFragment();
  const ts = nowStr();
  pending.forEach(text => {
    const div = document.createElement('div');
    div.className = 'log-entry';
    const time = document.createElement('span');
    time.className = 'log-time';
    time.textContent = ts;
    const msg = document.createElement('span');
    msg.className = 'log-msg';
    msg.textContent = text;
    div.appendChild(time);
    div.appendChild(msg);
    frag.appendChild(div);
  });
  body.appendChild(frag);
  // 只保留最近 LOG_DOM_MAX 行，避免长任务把日志面板撑成上万个节点
  while (body.childElementCount > LOG_DOM_MAX) {
    body.removeChild(body.firstElementChild);
  }
  body.scrollTop = body.scrollHeight;
  // 日志是在第一个 rAF 里才真正插入 DOM 的；如果滚动 rAF 先于本帧执行，
  // 它算出的 scrollHeight 还不含这些日志。补一次跟随滚动，避免停在半截。
  if (state.followTail) scrollToBottom();
}

function _enqueueLogRender(text) {
  _pendingLogs.push(text);
  if (_logFlushScheduled) return;
  _logFlushScheduled = true;
  requestAnimationFrame(_flushLogs);
}

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
    if (typeof clearChatInner === 'function') clearChatInner();
    else document.getElementById('chatInner').innerHTML = '';
    if (typeof clearAllChartThumbs === 'function') clearAllChartThumbs();
    showWelcome();
    state.activeTaskEl = null;
    state.activeLogs = [];
    _pendingLogs = [];
    if (typeof resetAssets === 'function') resetAssets();
    // 关闭旧任务的 trace / 阶段计时，避免新会话里混入上一个任务的事件
    _traceQueue = [];
    _pendingToken = null;
    if (window.app.stopTrace) window.app.stopTrace();
    if (window.app.stopStageTimer) window.app.stopStageTimer();
    state.followTail = true;
    state.unread = 0;
    state.autoOpenLogs = true;
    updateScrollButton();
    if (typeof focusPrompt === 'function') focusPrompt();
  },

  startTaskMessage(text, autoOpenLogs) {
    hideWelcome();
    const el = buildAiTaskMessage(text);
    document.getElementById('chatInner').appendChild(el);
    state.activeTaskEl = el;
    state.activeLogs = [];
    state.autoOpenLogs = autoOpenLogs !== false;
    _traceQueue = [];
    _pendingToken = null;
    scrollToBottom();
  },

  appendLog(text) {
    state.activeLogs.push(text);
    if (state.activeLogs.length > LOG_BUFFER_MAX) {
      state.activeLogs.splice(0, state.activeLogs.length - LOG_BUFFER_MAX);
    }
    // trace 订阅由 Rust 在 TaskStarted 时结构化下发（subscribeTrace）；
    // 不要再从日志文本猜测 task_id——恢复历史时老日志会误连到已结束的任务。
    _enqueueLogRender(text);
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
    if (parsed.conversationId) state.conversationId = parsed.conversationId;
    window.app.stopStageTimer();
    if (window.app.stopTrace) window.app.stopTrace();
    state.lastChartData = parsed;
    if (state.activeTaskEl) {
      const context = state.activeTaskEl.querySelector('.task-context');
      if (context) renderContextCards(context, parsed.contextCards || [], { interactive: true });
      const container = state.activeTaskEl.querySelector('.task-charts');
      if (container) renderChartGrid(container, parsed.items || []);
      const summary = state.activeTaskEl.querySelector('.task-summary');
      if (summary) {
        const total = (parsed.items || []).length;
        summary.textContent = '任务完成，共生成 ' + total + ' 个图表。';
      }
      const typing = state.activeTaskEl.querySelector('.typing');
      if (typing) typing.style.display = 'none';
      // 生成过程中日志面板是自动展开的；成功后收起，让“滚到底部”落在图表卡片上，
      // 想看执行细节仍可点“查看 Agent 执行日志”。失败时保持展开便于排查。
      const logBody = state.activeTaskEl.querySelector('.agent-log-body');
      const logToggle = state.activeTaskEl.querySelector('.agent-log-toggle');
      if (logToggle) {
        logToggle.classList.remove('expanded');
        logToggle.setAttribute('aria-expanded', 'false');
      }
      if (logBody) logBody.classList.remove('show');
      state.autoOpenLogs = false;
    }
    if (state.conversationId && typeof loadConversationAssets === 'function') {
      loadConversationAssets();
    }
    scrollToBottom();
  },

  failTask(err) {
    window.app.stopStageTimer();
    if (window.app.stopTrace) window.app.stopTrace();
    // 失败原因同时用 toast 提示：此时视图通常停在日志底部，任务摘要可能已被滚出屏幕
    const brief = String(err || '任务失败');
    window.app.showToast(brief.length > 140 ? brief.slice(0, 140) + '…' : brief, 'error');
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
    if (state.conversationId && typeof loadConversationAssets === 'function') {
      loadConversationAssets();
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
    // 新项目打开时清掉上一个项目的搜索/批量选择，避免把旧选择带进来
    state.fileFilter = '';
    state.fileSelectMode = false;
    state.selectedFilePaths = [];
    const search = document.querySelector('#fileSearchBox input');
    if (search) search.value = '';
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

  // 数据库「测试连接」返回的表列表（settings.js 负责渲染）
  showDbTables(jsonStr) {
    renderDbTablesResult(jsonStr);
  },

  showToast(message, type) {
    const c = document.getElementById('toastContainer');
    if (!c) return;
    // 同屏最多 TOAST_MAX 条，超出先移除最老的，避免刷屏遮挡界面
    while (c.children.length >= TOAST_MAX) c.removeChild(c.firstChild);
    const d = document.createElement('div');
    d.className = 'toast ' + (type || 'info');
    d.setAttribute('role', type === 'error' ? 'alert' : 'status');
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

  setCurrentConversation(conversationId) {
    if (typeof setCurrentConversation === 'function') {
      setCurrentConversation(conversationId);
    } else {
      state.conversationId = conversationId || null;
    }
  },

  setConversationAssets(jsonStr) {
    if (typeof setConversationAssets === 'function') setConversationAssets(jsonStr);
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
    if (window.app.stopTrace) window.app.stopTrace();
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

    // 1. 清空消息（保留欢迎页节点，方便之后“新对话”恢复）
    if (typeof clearChatInner === 'function') clearChatInner();
    else document.getElementById('chatInner').innerHTML = '';
    if (typeof clearAllChartThumbs === 'function') clearAllChartThumbs();
    state.activeTaskEl = null;
    state.activeLogs = [];
    _pendingLogs = [];
    state.conversationId = d.conversation_id || null;
    state.assets = [];
    state.assetsLoading = false;
    if (typeof renderAssets === 'function') renderAssets();
    state.followTail = true;
    state.unread = 0;
    state.autoOpenLogs = true;
    updateScrollButton();
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
    window.app.startTaskMessage(taskText, false);

    // 4. 还原 Agent 日志
    if (d.agent_logs && d.agent_logs.length > 0) {
      d.agent_logs.forEach(log => window.app.appendLog(log));
    }

    // 5. 根据状态完成或失败
    if (status === 'success') {
      const items = d.chart_items || [];
      window.app.completeTask(JSON.stringify({
        type: 'charts',
        items: items,
        contextCards: d.context_cards || [],
        conversationId: d.conversation_id || '',
      }));
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

    // 成功路径由 completeTask 统一刷新；失败/进行中的历史对话在这里补一次
    if (status !== 'success') {
      if (state.conversationId && typeof loadConversationAssets === 'function') {
        loadConversationAssets();
      } else if (typeof resetAssets === 'function') {
        resetAssets();
      }
    }
    scrollToBottom({ force: true });
  },
};
