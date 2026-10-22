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
    // chartId：后端直接给；旧消息从预览路径解析（/api/chart/<文件名>）
    if (!item.chartId && item.path) {
      const m = String(item.path).match(/\/api\/chart\/(.+)$/);
      if (m) { try { item.chartId = decodeURIComponent(m[1]); } catch (e) { item.chartId = m[1]; } }
    }
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
    // 二次优化入口：点击后输入区进入优化模式（只改图形实现，不重跑数据）
    if (status === 'success' && item.chartId) {
      const ob = document.createElement('button');
      ob.className = 'optimize-btn';
      ob.textContent = '🛠 优化';
      ob.title = '基于这张图提出修改（标题/配色/TopN…），只跑优化 agent';
      ob.onclick = function(ev) {
        ev.stopPropagation();
        setOptimizeTarget(item.chartId, item.title || item.chartId);
      };
      thumb.appendChild(ob);
    }
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

// ===== 上下文卡片：需求 / 数据 / 计划 / 校验 / 产物 =====
function contextKindMeta(kind) {
  const map = {
    request: { icon: '📝', label: '需求' },
    data: { icon: '📊', label: '数据' },
    plan: { icon: '🧭', label: '计划' },
    workflow: { icon: '🔁', label: '工作流' },
    validation: { icon: '✅', label: '校验' },
    artifact: { icon: '📁', label: '产物' },
  };
  return map[kind] || { icon: '•', label: '信息' };
}

function renderContextCards(container, cards, options) {
  if (!container) return;
  const interactive = !options || options.interactive !== false;
  container.innerHTML = '';
  if (!cards || cards.length === 0) {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'block';

  const panel = document.createElement('details');
  panel.className = 'context-panel';
  panel.open = true;

  const summary = document.createElement('summary');
  summary.className = 'context-summary';
  const errorCount = cards.filter(c => c.status === 'error').length;
  const warnCount = cards.filter(c => c.status === 'warning').length;
  let summaryText = '方案与校验 · ' + cards.length + ' 项';
  if (errorCount > 0) summaryText += ' · ' + errorCount + ' 个错误';
  else if (warnCount > 0) summaryText += ' · ' + warnCount + ' 个提示';
  summary.textContent = summaryText;
  panel.appendChild(summary);

  const grid = document.createElement('div');
  grid.className = 'context-grid';
  cards.forEach(card => {
    const el = document.createElement('div');
    el.className = 'context-card context-' + (card.status || 'info');

    const header = document.createElement('div');
    header.className = 'context-card-header';
    const dot = document.createElement('span');
    dot.className = 'context-dot';
    const meta = contextKindMeta(card.kind);
    const title = document.createElement('span');
    title.className = 'context-card-title';
    title.textContent = meta.icon + ' ' + (card.title || meta.label);
    header.appendChild(dot);
    header.appendChild(title);
    el.appendChild(header);

    if (card.text) {
      const text = document.createElement('div');
      text.className = 'context-card-text';
      text.textContent = card.text;
      el.appendChild(text);
    }
    if (card.items && card.items.length > 0) {
      const list = document.createElement('ul');
      list.className = 'context-card-items';
      card.items.slice(0, 8).forEach(item => {
        const li = document.createElement('li');
        li.textContent = item;
        list.appendChild(li);
      });
      el.appendChild(list);
    }
    if (
      interactive &&
      card.kind === 'plan' &&
      card.meta &&
      Array.isArray(card.meta.clarification) &&
      card.meta.clarification.length > 0
    ) {
      const action = document.createElement('button');
      action.className = 'context-action';
      action.textContent = '补充说明';
      action.title = '恢复本次数据源，并在输入框中继续调整';
      action.addEventListener('click', () => {
        const input = document.getElementById('prompt-input');
        if (!input) return;
        if (state.lastFiles && state.lastFiles.length > 0) {
          state.files = state.lastFiles.map(f => (typeof f === 'object' ? { ...f } : f));
          if (typeof renderFileChips === 'function') renderFileChips();
        }
        input.value = '在“' + (card.title || '刚才的图表') + '”的基础上调整：';
        if (typeof autoResize === 'function') autoResize(input);
        input.focus();
        if (input.scrollIntoView) input.scrollIntoView({ block: 'nearest' });
      });
      el.appendChild(action);
    }
    grid.appendChild(el);
  });
  panel.appendChild(grid);
  container.appendChild(panel);
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

function revealChartInFolder() {
  const src = document.getElementById('cvIframe').src || '';
  const m = src.match(/\/api\/chart\/(.+)$/);
  if (m && m[1]) sendToRust('revealChart', { chartId: decodeURIComponent(m[1]) });
}
