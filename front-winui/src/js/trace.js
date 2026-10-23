// ===== Trace WebSocket 全链路监控（从 api.js 拆分）=====
// 扩展 window.app：订阅 /ws/trace，实时显示 trace/token/error 事件。
// 断线时按指数退避重连（任务仍在执行时），任务结束后由 stopTrace 停止。

window.app._traceWs = null;
window.app._traceTaskId = null;
window.app._traceRetries = 0;
window.app._traceTokenTotal = 0;
window.app._traceTokenCalls = 0;

const TRACE_RECONNECT_MAX = 5;

// Trace 事件可能非常密集，合并到一次 rAF 内批量插入时间线节点。
let _traceQueue = [];
let _traceFlushScheduled = false;
let _pendingToken = null;
let _tokenScheduled = false;

function _flushTraceNodes() {
  _traceFlushScheduled = false;
  if (_traceQueue.length === 0 || !state.activeTaskEl) { _traceQueue = []; return; }
  const timeline = state.activeTaskEl.querySelector('.trace-timeline');
  if (!timeline) { _traceQueue = []; return; }
  const queue = _traceQueue;
  _traceQueue = [];
  const frag = document.createDocumentFragment();
  queue.forEach(event => {
    const node = document.createElement('div');
    node.className = 'trace-node trace-' + (event.status || '');
    const parts = [
      ['trace-time', (event.timestamp || '').slice(11, 19)],
      ['trace-file', event.file_name || ''],
      ['trace-func', event.func_name || ''],
      ['trace-dur', (event.duration_ms || 0) + 'ms'],
      ['trace-stat', event.status || ''],
    ];
    parts.forEach(([cls, text]) => {
      const span = document.createElement('span');
      span.className = cls;
      span.textContent = text;
      node.appendChild(span);
    });
    if (event.error) node.title = event.error;
    frag.appendChild(node);
  });
  timeline.appendChild(frag);
  while (timeline.childElementCount > TRACE_DOM_MAX) {
    timeline.removeChild(timeline.firstElementChild);
  }
  timeline.scrollTop = timeline.scrollHeight;
}

window.app.subscribeTrace = function(taskId) {
  if (!taskId) return;
  window.app._traceTaskId = taskId;
  window.app._traceRetries = 0;
  window.app._traceTokenTotal = 0;
  window.app._traceTokenCalls = 0;
  window.app._openTraceSocket(taskId);
};

window.app._openTraceSocket = function(taskId) {
  if (window.app._traceWs) {
    try { window.app._traceWs.close(); } catch(e) {}
    window.app._traceWs = null;
  }
  try {
    const base = (state.backendUrl || 'http://127.0.0.1:5000').replace(/\/$/, '');
    const wsUrl = base.replace(/^http/, 'ws') + '/ws/trace/' + taskId;
    const ws = new WebSocket(wsUrl);
    window.app._traceWs = ws;
    window.app.stopStageTimer();

    ws.onmessage = function(event) {
      let data;
      try { data = JSON.parse(event.data); } catch(e) { return; }
      if (data.type === 'trace') window.app.onTraceEvent(data);
      else if (data.type === 'token') window.app.onTokenEvent(data);
      else if (data.type === 'error') window.app.onErrorEvent(data);
      else if (data.type === 'error_summary') window.app.onErrorSummary(data);
      else if (data.type === 'stage') window.app.onStageEvent(data);
    };

    ws.onerror = function() {
      console.warn('[Trace WS] error');
    };

    // 任务仍在执行时断线自动重连（400ms→8s 退避，最多 5 次）
    ws.onclose = function() {
      window.app._traceWs = null;
      if (window.app._traceTaskId !== taskId) return; // 已切换/结束
      const retries = window.app._traceRetries || 0;
      if (retries >= TRACE_RECONNECT_MAX) return;
      window.app._traceRetries = retries + 1;
      const delay = Math.min(1000 * Math.pow(2, retries), 8000);
      setTimeout(function() {
        if (window.app._traceTaskId === taskId) window.app._openTraceSocket(taskId);
      }, delay);
    };
  } catch(e) {
    console.warn('[Trace WS] connect failed:', e);
  }
};

window.app.stopTrace = function() {
  window.app._traceTaskId = null;
  window.app._traceRetries = 0;
  if (window.app._traceWs) {
    try { window.app._traceWs.close(); } catch(e) {}
    window.app._traceWs = null;
  }
};

window.app.onTraceEvent = function(event) {
  if (!state.activeTaskEl) return;
  _traceQueue.push(event);
  if (_traceFlushScheduled) return;
  _traceFlushScheduled = true;
  requestAnimationFrame(_flushTraceNodes);
};

window.app.onTokenEvent = function(event) {
  if (!state.activeTaskEl) return;
  // 网关按 token 推送，可能每秒几十次；合并到一帧更新一次文本
  _pendingToken = event;
  if (_tokenScheduled) return;
  _tokenScheduled = true;
  requestAnimationFrame(function() {
    _tokenScheduled = false;
    const ev = _pendingToken;
    _pendingToken = null;
    if (!ev || !state.activeTaskEl) return;
    window.app._traceTokenTotal = ev.cumulative_total || 0;
    window.app._traceTokenCalls = (ev.call_index || 0) + 1;
    const counter = state.activeTaskEl.querySelector('.token-counter');
    if (counter) {
      counter.textContent = '\u{1F511} ' + window.app._traceTokenTotal + ' tokens (' + window.app._traceTokenCalls + ' calls) ¥' + (ev.cost_rmb || 0).toFixed(4);
    }
  });
};

window.app.onErrorEvent = function(event) {
  if (!state.activeTaskEl) return;
  const panel = state.activeTaskEl.querySelector('.error-panel');
  if (!panel) return;
  panel.style.display = 'block';

  const chainHtml = (event.call_chain || []).map(function(f) {
    return '<span class="chain-func">' + escHtml(f) + '</span>';
  }).join(' <span class="chain-arrow">→</span> ');

  const framesHtml = (event.traceback_frames || []).map(function(f) {
    return '<div class="stack-frame">' +
      '<span class="stack-file">' + escHtml(f.file) + ':' + escHtml(f.line) + '</span>' +
      '<span class="stack-func">' + escHtml(f.func) + '()</span>' +
      (f.code ? '<code class="stack-code">' + escHtml(f.code) + '</code>' : '') +
      '</div>';
  }).join('');

  const varsHtml = Object.keys(event.local_vars || {}).map(function(k) {
    return '<div class="var-row"><span class="var-key">' + escHtml(k) + '</span> = <span class="var-val">' + escHtml(event.local_vars[k]) + '</span></div>';
  }).join('');

  panel.innerHTML =
    '<div class="error-header">' +
      '<span class="error-type">' + escHtml(event.error_type || 'Unknown') + '</span>' +
      '<span class="error-cat tag-' + escAttr(event.error_category || 'unknown') + '">' + escHtml(event.error_category || 'unknown') + '</span>' +
    '</div>' +
    '<div class="error-loc">' + escHtml(event.file_name || '') + ' :: ' + escHtml(event.func_name || '') + '</div>' +
    '<div class="error-msg">' + escHtml(event.error_message || '') + '</div>' +
    (chainHtml ? '<div class="error-section"><div class="section-title">调用链</div><div class="call-chain">' + chainHtml + '</div></div>' : '') +
    (framesHtml ? '<div class="error-section"><div class="section-title">堆栈</div><div class="stack-trace">' + framesHtml + '</div></div>' : '') +
    (varsHtml ? '<div class="error-section"><div class="section-title">局部变量</div><div class="local-vars">' + varsHtml + '</div></div>' : '');
};

window.app.onErrorSummary = function(event) {
  if (!state.activeTaskEl) return;
  var summary = state.activeTaskEl.querySelector('.error-summary');
  if (summary && event.total_errors > 0) {
    var cats = Object.keys(event.by_category || {}).join(', ');
    summary.textContent = '⚠ ' + event.total_errors + ' errors (' + cats + ')';
    summary.style.display = 'block';
  }
};

// ===== 阶段计时监控：当前阶段 + 实时秒数 + 各阶段耗时 =====
window.app._stageInterval = null;
window.app._stageStartedAt = 0;

window.app.stopStageTimer = function() {
  if (window.app._stageInterval) {
    clearInterval(window.app._stageInterval);
    window.app._stageInterval = null;
  }
  window.app._stageStartedAt = 0;
};

window.app.onStageEvent = function(event) {
  if (!state.activeTaskEl) return;
  var current = state.activeTaskEl.querySelector('.stage-current');
  var labelEl = state.activeTaskEl.querySelector('.stage-current-label');
  var secEl = state.activeTaskEl.querySelector('.stage-current-sec');
  var list = state.activeTaskEl.querySelector('.stage-list');
  var total = state.activeTaskEl.querySelector('.stage-total');

  if (event.event === 'start') {
    window.app.stopStageTimer();
    window.app._stageStartedAt = Date.now();
    if (labelEl) labelEl.textContent = event.label || event.stage || '';
    if (current) {
      current.style.display = 'flex';
      current.classList.add('running');
    }
    // 同步进度条标签
    var progLabel = state.activeTaskEl.querySelector('.progress-label');
    if (progLabel) progLabel.textContent = '当前阶段: ' + (event.label || event.stage);
    window.app._stageInterval = setInterval(function() {
      if (!window.app._stageStartedAt || !state.activeTaskEl) return;
      var el = state.activeTaskEl.querySelector('.stage-current-sec');
      if (el) el.textContent = ((Date.now() - window.app._stageStartedAt) / 1000).toFixed(1) + 's';
    }, 200);

  } else if (event.event === 'end') {
    window.app.stopStageTimer();
    if (current) current.classList.remove('running');
    if (secEl) secEl.textContent = '';
    if (labelEl) labelEl.textContent = '阶段切换中...';
    if (list && event.duration_s != null) {
      var row = document.createElement('div');
      row.className = 'stage-row' + (event.status === 'failed' ? ' stage-failed' : '');
      row.innerHTML =
        '<span class="stage-mark">' + (event.status === 'failed' ? '✕' : '✓') + '</span>' +
        '<span class="stage-name"></span>' +
        '<span class="stage-dur">' + Number(event.duration_s).toFixed(1) + 's</span>';
      row.querySelector('.stage-name').textContent = event.label || event.stage;
      list.appendChild(row);
    }

  } else if (event.event === 'summary') {
    window.app.stopStageTimer();
    if (current) current.style.display = 'none';
    if (total && event.total_s != null) {
      total.textContent = '⏱ 全流程总计 ' + Number(event.total_s).toFixed(1) + 's';
      total.style.display = 'block';
    }
  }
};
