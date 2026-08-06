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
