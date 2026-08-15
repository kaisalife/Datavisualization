// ===== 消息构建与渲染 =====
function showWelcome() {
  const w = document.getElementById('welcomeState');
  if (w) w.style.display = 'flex';
}

function hideWelcome() {
  const w = document.getElementById('welcomeState');
  if (w) w.style.display = 'none';
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
    '<div class="task-charts"></div>' +
    '<div class="msg-actions"><button class="msg-action-btn" onclick="copyLastCharts()">复制</button></div>';
  msg.innerHTML = '<div class="msg-avatar ai">📊</div>';
  msg.appendChild(content);
  area.appendChild(msg);
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
    '<div class="task-charts"></div>' +
    '<div class="task-summary" style="font-size:13px;color:var(--text-secondary);margin-top:6px"></div>' +
    '<div class="agent-log-toggle" onclick="toggleLog(this)"><svg class="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>查看 Agent 执行日志</div>' +
    '<div class="agent-log-body"></div>' +
    '<div class="trace-toggle" onclick="toggleTrace(this)"><svg class="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>执行轨迹</div>' +
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
  const body = el.nextElementSibling;
  if (body) body.classList.toggle('show');
}

function toggleTrace(el) {
  el.classList.toggle('expanded');
  var next = el.nextElementSibling;
  if (next) {
    if (next.classList.contains('trace-timeline')) {
      next.classList.toggle('show');
    }
  }
}

function copyActiveLogs() {
  const text = state.activeLogs.join('\n');
  navigator.clipboard.writeText(text).then(() => window.app.showToast('日志已复制', 'success'));
}

function copyLastCharts() {
  navigator.clipboard.writeText('图表链接已复制').then(() => window.app.showToast('已复制', 'success'));
}

function regenerate() {
  window.app.showToast('请重新发送需求以重新生成', 'info');
}
