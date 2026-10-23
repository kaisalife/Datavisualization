// ===== 消息构建与渲染 =====
function showWelcome() {
  const w = document.getElementById('welcomeState');
  if (w) w.style.display = 'flex';
}

function hideWelcome() {
  const w = document.getElementById('welcomeState');
  if (w) w.style.display = 'none';
}

// 清空聊天区，但保留欢迎页节点（它就在 #chatInner 里；直接 innerHTML='' 会把它一起删掉，
// “新对话”后就再也回不到欢迎页/建议卡片了）。
function clearChatInner() {
  const inner = document.getElementById('chatInner');
  if (!inner) return;
  Array.from(inner.children).forEach(el => {
    if (el.id !== 'welcomeState') inner.removeChild(el);
  });
}

function appendMessage(role, content, kind) {
  const area = document.getElementById('chatInner');
  const msg = document.createElement('div');
  msg.className = 'msg ' + (role === 'user' ? 'user' : 'ai');
  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar ' + (role === 'user' ? 'user' : 'ai');
  avatar.textContent = role === 'user' ? 'K' : '📊';
  const contentEl = document.createElement('div');
  contentEl.className = 'msg-content';
  const name = document.createElement('div');
  name.className = 'msg-name';
  name.textContent = role === 'user' ? '你' : 'DataVisualServer';
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  if (kind === 'code') {
    try {
      const parsed = JSON.parse(content);
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.textContent = parsed.code;
      pre.appendChild(code);
      bubble.appendChild(pre);
    } catch(e) {
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.textContent = content;
      pre.appendChild(code);
      bubble.appendChild(pre);
    }
  } else {
    bubble.textContent = content;
  }
  contentEl.appendChild(name);
  contentEl.appendChild(bubble);
  msg.appendChild(avatar);
  msg.appendChild(contentEl);
  area.appendChild(msg);
}

function appendAiChartsMessage(parsed) {
  state.lastChartData = parsed;
  const area = document.getElementById('chatInner');
  const msg = document.createElement('div');
  msg.className = 'msg ai';
  const content = document.createElement('div');
  content.className = 'msg-content';
  content.innerHTML =
    '<div class="msg-name">DataVisualServer</div>' +
    '<div class="msg-bubble">已为你生成以下图表，点击卡片可全屏预览。</div>' +
    '<div class="task-context"></div>' +
    '<div class="task-charts"></div>' +
    '<div class="msg-actions"><button type="button" class="msg-action-btn" data-tip="复制本次图表的访问链接" aria-label="复制本次图表链接" onclick="copyLastCharts()">复制链接</button></div>';
  msg.innerHTML = '<div class="msg-avatar ai">📊</div>';
  msg.appendChild(content);
  area.appendChild(msg);
  renderContextCards(msg.querySelector('.task-context'), parsed.contextCards || [], { interactive: false });
  renderChartGrid(msg.querySelector('.task-charts'), parsed.items || []);
}

function buildAiTaskMessage(text) {
  const msg = document.createElement('div');
  msg.className = 'msg ai';
  const content = document.createElement('div');
  content.className = 'msg-content';
  content.innerHTML =
    '<div class="msg-name">DataVisualServer</div>' +
    '<div class="msg-bubble"></div>' +
    '<div class="typing"><span></span><span></span><span></span></div>' +
    '<div class="msg-progress"><div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>' +
      '<div class="progress-text"><span class="progress-label">准备中...</span><span></span></div></div>' +
    '<div class="stage-panel">' +
      '<div class="stage-current"><span class="stage-dot"></span><span class="stage-current-label">等待阶段信息...</span><span class="stage-current-sec"></span></div>' +
      '<div class="stage-list"></div>' +
      '<div class="stage-total" style="display:none"></div>' +
    '</div>' +
    '<div class="task-context"></div>' +
    '<div class="task-charts"></div>' +
    '<div class="task-summary" style="font-size:13px;color:var(--text-secondary);margin-top:6px"></div>' +
    '<button type="button" class="agent-log-toggle" aria-expanded="false" onclick="toggleLog(this)"><svg class="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>查看 Agent 执行日志</button>' +
    '<div class="agent-log-body"></div>' +
    '<button type="button" class="trace-toggle" aria-expanded="false" onclick="toggleTrace(this)"><svg class="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>执行轨迹</button>' +
    '<div class="trace-timeline"></div>' +
    '<div class="token-counter">0 tokens</div>' +
    '<div class="error-panel" style="display:none"></div>' +
    '<div class="error-summary" style="display:none"></div>' +
    '<div class="msg-actions">' +
      '<button class="msg-action-btn" onclick="copyActiveLogs()">复制日志</button>' +
      '<button class="msg-action-btn" onclick="regenerate()">重新生成</button>' +
    '</div>';
  content.querySelector('.msg-bubble').textContent = text || '正在为你生成图表，首先对数据进行质量检查和清洗，然后基于数据特征生成可视化方案。';
  msg.innerHTML = '<div class="msg-avatar ai">📊</div>';
  msg.appendChild(content);
  return msg;
}

function toggleLog(el) {
  el.classList.toggle('expanded');
  el.setAttribute('aria-expanded', el.classList.contains('expanded') ? 'true' : 'false');
  const body = el.nextElementSibling;
  if (body) body.classList.toggle('show');
}

function toggleTrace(el) {
  el.classList.toggle('expanded');
  el.setAttribute('aria-expanded', el.classList.contains('expanded') ? 'true' : 'false');
  var next = el.nextElementSibling;
  if (next) {
    if (next.classList.contains('trace-timeline')) {
      next.classList.toggle('show');
    }
  }
}

function copyActiveLogs() {
  const text = state.activeLogs.join('\n');
  copyText(text)
    .then(() => window.app.showToast('日志已复制', 'success'))
    .catch(() => window.app.showToast('复制失败，请手动选择日志文本', 'error'));
}

function copyLastCharts() {
  const items = (state.lastChartData && state.lastChartData.items) || [];
  const base = String(state.backendUrl || '').replace(/\/+$/, '');
  const links = items
    .filter(item => item && item.path)
    .map(item => {
      const path = String(item.path);
      const url = /^https?:\/\//i.test(path) ? path : base + (path.charAt(0) === '/' ? path : '/' + path);
      return (item.title || item.chartType || '图表') + '：' + url;
    });
  if (links.length === 0) {
    window.app.showToast('没有可复制的图表链接', 'info');
    return;
  }
  copyText(links.join('\n'))
    .then(() => window.app.showToast('图表链接已复制', 'success'))
    .catch(() => window.app.showToast('复制失败，请稍后重试', 'error'));
}

function regenerate() {
  window.app.showToast('请重新发送需求以重新生成', 'info');
}
