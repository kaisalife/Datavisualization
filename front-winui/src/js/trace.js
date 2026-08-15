// ===== Trace WebSocket 全链路监控（从 api.js 拆分）=====
// 扩展 window.app：订阅 /ws/trace，实时显示 trace/token/error 事件。

window.app._traceWs = null;
window.app._traceTokenTotal = 0;
window.app._traceTokenCalls = 0;

window.app.subscribeTrace = function(taskId) {
  // 关闭旧连接
  if (window.app._traceWs) {
    try { window.app._traceWs.close(); } catch(e) {}
    window.app._traceWs = null;
  }
  window.app._traceTokenTotal = 0;
  window.app._traceTokenCalls = 0;

  try {
    const base = (state.backendUrl || 'http://127.0.0.1:5000').replace(/\/$/, '');
    const wsUrl = base.replace(/^http/, 'ws') + '/ws/trace/' + taskId;
    const ws = new WebSocket(wsUrl);
    window.app._traceWs = ws;
    window.app.stopStageTimer();

    ws.onmessage = function(event) {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'trace') {
          window.app.onTraceEvent(data);
        } else if (data.type === 'token') {
          window.app.onTokenEvent(data);
        } else if (data.type === 'error') {
          window.app.onErrorEvent(data);
        } else if (data.type === 'error_summary') {
          window.app.onErrorSummary(data);
        } else if (data.type === 'stage') {
          window.app.onStageEvent(data);
        }
      } catch(e) { /* ignore parse errors */ }
    };

    ws.onerror = function() {
      console.warn('[Trace WS] error');
    };

    ws.onclose = function() {
      window.app._traceWs = null;
    };
  } catch(e) {
    console.warn('[Trace WS] connect failed:', e);
  }
};

window.app.onTraceEvent = function(event) {
  if (!state.activeTaskEl) return;
  const timeline = state.activeTaskEl.querySelector('.trace-timeline');
  if (!timeline) return;

  const node = document.createElement('div');
  node.className = 'trace-node trace-' + event.status;
  const ts = (event.timestamp || '').slice(11, 19);
  node.innerHTML =
    '<span class="trace-time">' + ts + '</span>' +
    '<span class="trace-file">' + (event.file_name || '') + '</span>' +
    '<span class="trace-func">' + (event.func_name || '') + '</span>' +
    '<span class="trace-dur">' + (event.duration_ms || 0) + 'ms</span>' +
    '<span class="trace-stat">' + (event.status || '') + '</span>';
  if (event.error) {
    node.title = event.error;
  }
  timeline.appendChild(node);
  timeline.scrollTop = timeline.scrollHeight;
};

window.app.onTokenEvent = function(event) {
  if (!state.activeTaskEl) return;
  window.app._traceTokenTotal = event.cumulative_total || 0;
  window.app._traceTokenCalls = (event.call_index || 0) + 1;
  const counter = state.activeTaskEl.querySelector('.token-counter');
  if (counter) {
    counter.textContent = '\u{1F511} ' + window.app._traceTokenTotal + ' tokens (' + window.app._traceTokenCalls + ' calls) ¥' + (event.cost_rmb || 0).toFixed(4);
  }
};

window.app.onErrorEvent = function(event) {
  if (!state.activeTaskEl) return;
  const panel = state.activeTaskEl.querySelector('.error-panel');
  if (!panel) return;
  panel.style.display = 'block';

  var chainHtml = (event.call_chain || []).map(function(f) {
    return '<span class="chain-func">' + f + '</span>';
  }).join(' <span class="chain-arrow">→</span> ');

  var framesHtml = (event.traceback_frames || []).map(function(f) {
    return '<div class="stack-frame">' +
      '<span class="stack-file">' + f.file + ':' + f.line + '</span>' +
      '<span class="stack-func">' + f.func + '()</span>' +
      (f.code ? '<code class="stack-code">' + f.code.replace(/</g, '&lt;') + '</code>' : '') +
      '</div>';
  }).join('');

  var varsHtml = Object.keys(event.local_vars || {}).map(function(k) {
    return '<div class="var-row"><span class="var-key">' + k + '</span> = <span class="var-val">' + event.local_vars[k] + '</span></div>';
  }).join('');

  panel.innerHTML =
    '<div class="error-header">' +
      '<span class="error-type">' + (event.error_type || 'Unknown') + '</span>' +
      '<span class="error-cat tag-' + (event.error_category || 'unknown') + '">' + (event.error_category || 'unknown') + '</span>' +
    '</div>' +
    '<div class="error-loc">' + (event.file_name || '') + ' :: ' + (event.func_name || '') + '</div>' +
    '<div class="error-msg">' + (event.error_message || '') + '</div>' +
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
