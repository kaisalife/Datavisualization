// ===== 图表卡片网格 =====
function renderChartGrid(container, items) {
  if (!items || items.length === 0) { container.innerHTML = ''; return; }
  const grid = document.createElement('div');
  grid.className = 'chart-grid';
  items.forEach((item, i) => {
    const card = document.createElement('div');
    card.className = 'chart-card';
    const status = item.status || 'success';
    const badgeCls = status === 'success' ? 'badge-success' : 'badge-failed';
    const badgeTxt = status === 'success' ? '✓' : '✗';
    const thumb = document.createElement('div');
    thumb.className = 'chart-card-thumb';
    if (status === 'success' && item.path) {
      const wrap = document.createElement('div');
      wrap.className = 'chart-card-iframe';
      const ifr = document.createElement('iframe');
      ifr.src = item.path;
      ifr.loading = 'lazy';
      ifr.sandbox = 'allow-scripts allow-same-origin';
      wrap.appendChild(ifr);
      thumb.appendChild(wrap);
    } else {
      const fail = document.createElement('div');
      fail.className = 'chart-card-failed';
      fail.innerHTML = '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--error)" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg><span>生成失败</span>';
      thumb.appendChild(fail);
    }
    const badge = document.createElement('div');
    badge.className = 'chart-card-badge ' + badgeCls;
    badge.textContent = badgeTxt;
    thumb.appendChild(badge);
    const info = document.createElement('div');
    info.className = 'chart-card-info';
    const typeEl = document.createElement('div');
    typeEl.className = 'chart-card-type';
    typeEl.textContent = item.chartType || '图表';
    const tag = document.createElement('span');
    tag.className = 'chart-type-tag';
    tag.textContent = item.chartType || '';
    typeEl.appendChild(tag);
    const titleEl = document.createElement('div');
    titleEl.className = 'chart-card-title';
    titleEl.textContent = item.title || item.path || '';
    info.appendChild(typeEl);
    info.appendChild(titleEl);
    card.appendChild(thumb);
    card.appendChild(info);
    if (status === 'success') {
      card.onclick = function() { openChartViewer(item); };
    }
    grid.appendChild(card);
  });
  container.innerHTML = '';
  container.appendChild(grid);
}

// ===== Chart Viewer 全屏查看器 =====
function openChartViewer(item) {
  document.getElementById('cvTitle').textContent = item.title || item.chartType || '图表预览';
  document.getElementById('cvIframe').src = item.path || '';
  document.getElementById('cvType').textContent = item.chartType || '-';
  document.getElementById('cvStatus').innerHTML = item.status === 'success' ? '<span style="color:var(--success)">● 生成成功</span>' : '<span style="color:var(--error)">● 失败</span>';
  document.getElementById('cvFile').textContent = item.title || item.path || '-';
  document.getElementById('cvDesc').textContent = item.desc || '';
  const logsEl = document.getElementById('cvLogs');
  if (state.activeLogs.length > 0) {
    logsEl.innerHTML = '';
    state.activeLogs.forEach(l => {
      const div = document.createElement('div');
      div.className = 'log-entry';
      const t = document.createElement('span'); t.className = 'log-time'; t.textContent = '';
      const m = document.createElement('span'); m.className = 'log-msg'; m.textContent = l;
      div.appendChild(t); div.appendChild(m);
      logsEl.appendChild(div);
    });
  } else {
    logsEl.textContent = '暂无日志';
  }
  document.getElementById('cvCode').textContent = item.code || '暂无代码';
  document.getElementById('chartViewer').classList.add('show');
}

function closeChartViewer() {
  document.getElementById('chartViewer').classList.remove('show');
  document.getElementById('cvIframe').src = '';
}

function cvTab(tab, el) {
  document.querySelectorAll('.cv-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.cv-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('cvPanel-' + tab).classList.add('active');
}

function openChartNewTab() {
  const src = document.getElementById('cvIframe').src;
  if (src) sendToRust('openChart', { path: src });
}

function exportCurrentChart() {
  const src = document.getElementById('cvIframe').src || '';
  const m = src.match(/\/api\/chart\/(.+)$/);
  if (m && m[1]) sendToRust('exportChart', { chartId: decodeURIComponent(m[1]) });
}
