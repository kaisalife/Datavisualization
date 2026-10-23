// ===== 当前对话图表资产（列表 / 版本链 / 二次优化入口） =====
// 数据来自后端 /api/conversation-assets/<conversation_id>：
// 同一张图的 v0/v1/v2… 会通过 root_chart_id 归到一组。

function resetAssets() {
  state.conversationId = null;
  state.assets = [];
  state.assetsLoading = false;
  state.assetSelectMode = false;
  state.selectedAssetIds = [];
  state.assetVisibleIds = [];
  renderAssets();
}

function setCurrentConversation(conversationId) {
  state.conversationId = conversationId || null;
}

function loadConversationAssets() {
  if (!state.conversationId) {
    state.assets = [];
    state.assetsLoading = false;
    state.assetSelectMode = false;
    state.selectedAssetIds = [];
    state.assetVisibleIds = [];
    renderAssets();
    return;
  }
  state.assetsLoading = true;
  renderAssets();
  sendToRust('listConversationAssets', { conversationId: state.conversationId });
}

function refreshAssets() {
  loadConversationAssets();
}

function setConversationAssets(jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { data = { assets: [] }; }
  // 用户已经切到别的对话时，丢弃迟到的响应
  if (data.conversationId && state.conversationId && data.conversationId !== state.conversationId) {
    return;
  }
  if (!state.conversationId && data.conversationId) {
    state.conversationId = data.conversationId;
  }
  state.assets = Array.isArray(data.assets) ? data.assets : [];
  state.assetsLoading = false;
  const available = {};
  state.assets.forEach(item => { if (item && item.chart_id) available[item.chart_id] = true; });
  state.selectedAssetIds = (state.selectedAssetIds || []).filter(id => available[id]);
  renderAssets();
}

function assetChartPath(chartId) {
  const base = String(state.backendUrl || '').replace(/\/+$/, '');
  return base + '/api/chart/' + encodeURIComponent(chartId);
}

function _assetGroups() {
  const groups = [];
  const byRoot = {};
  (state.assets || []).forEach(item => {
    if (!item || !item.chart_id) return;
    const root = item.root_chart_id || item.chart_id;
    if (!byRoot[root]) {
      byRoot[root] = {
        root: root,
        title: item.title || item.chart_id,
        chartType: item.chart_type || '图表',
        versions: [],
      };
      groups.push(byRoot[root]);
    }
    byRoot[root].versions.push(item);
  });
  groups.forEach(group => {
    group.versions.sort((a, b) => (a.version || 0) - (b.version || 0));
  });
  return groups;
}

function _assetVersionLabel(version) {
  const v = Number(version) || 0;
  return v <= 0 ? '原图' : 'v' + v;
}

function _assetDate(value) {
  // 侧栏很窄，只保留“月-日 时:分”，完整时间对版本选择没有额外价值
  const text = String(value || '');
  if (text.length < 16) return '';
  return text.slice(5, 16).replace('T', ' ');
}

function renderAssets() {
  const list = document.getElementById('assetList');
  const countEl = document.getElementById('assetCount');
  const tabCount = document.getElementById('assetTabCount');
  if (!list) return;

  const assets = Array.isArray(state.assets) ? state.assets : [];
  state.assetVisibleIds = assets.filter(item => item && item.chart_id).map(item => item.chart_id);
  if (countEl) countEl.textContent = String(assets.length);
  if (tabCount) {
    tabCount.textContent = String(assets.length);
    tabCount.style.display = assets.length > 0 ? 'inline-flex' : 'none';
  }

  if (!state.conversationId) {
    state.assetSelectMode = false;
    state.selectedAssetIds = [];
    list.innerHTML = '<div class="asset-empty"><div class="asset-empty-icon">🗂️</div>' +
      '<div>当前对话还没有生成图表</div>' +
      '<div class="asset-empty-sub">发送需求后，生成的图表和优化版本会出现在这里</div></div>';
    renderAssetBatchBar();
    return;
  }

  if (state.assetsLoading) {
    list.innerHTML = '<div class="asset-empty"><div class="asset-empty-icon">⏳</div>' +
      '<div>正在加载图表资产…</div></div>';
    renderAssetBatchBar();
    return;
  }

  if (assets.length === 0) {
    state.assetSelectMode = false;
    state.selectedAssetIds = [];
    list.innerHTML = '<div class="asset-empty"><div class="asset-empty-icon">🗂️</div>' +
      '<div>这个对话还没有图表资产</div>' +
      '<div class="asset-empty-sub">任务完成后点击右上角刷新，或重新发送需求</div></div>';
    renderAssetBatchBar();
    return;
  }

  const groups = _assetGroups();
  const selected = state.selectedAssetIds || [];
  let html = '<div class="asset-summary"><span>' + groups.length + ' 张图 · ' + assets.length + ' 个版本</span>' +
    (state.assetSelectMode ? '<span class="asset-summary-tip">点击版本行即可多选</span>' : '') + '</div>';
  groups.forEach(group => {
    html += '<div class="asset-group">';
    html += '<div class="asset-group-head">' +
      '<span class="asset-group-icon" aria-hidden="true">📊</span>' +
      '<span class="asset-group-title" title="' + escAttr(group.title) + '">' + escHtml(group.title) + '</span>' +
      '<span class="asset-group-count" title="版本数">' + group.versions.length + '</span>' +
      '</div>';
    html += '<div class="asset-version-list">';
    group.versions.forEach(item => {
      const title = item.title || group.title || item.chart_id;
      const type = item.chart_type || group.chartType || '图表';
      const checked = state.assetSelectMode && selected.indexOf(item.chart_id) >= 0;
      const tip = item.optimize_prompt
        ? '优化指令：' + item.optimize_prompt
        : (Number(item.version) > 0 ? '二次优化版本' : '原始生成版本');
      const checkbox = state.assetSelectMode
        ? '<input type="checkbox" class="row-checkbox" data-action="toggle" tabindex="-1" aria-label="选择 ' + escAttr(title) + ' ' + escAttr(_assetVersionLabel(item.version)) + '"' + (checked ? ' checked' : '') + '>'
        : '';
      const actions = state.assetSelectMode ? '' :
        '<span class="asset-version-actions">' +
          '<button type="button" class="asset-action-btn" data-action="view" data-chart="' + escAttr(item.chart_id) + '" data-title="' + escAttr(title) + '" data-type="' + escAttr(type) + '" data-tip="全屏查看这张图" aria-label="查看图表">查看</button>' +
          '<button type="button" class="asset-action-btn primary" data-action="optimize" data-chart="' + escAttr(item.chart_id) + '" data-title="' + escAttr(title) + '" data-tip="把这张图加入输入区，发送修改要求（只重新渲染这张图）" aria-label="优化这张图表">优化</button>' +
        '</span>';
      html += '<div class="asset-version-row' + (checked ? ' selected' : '') + '" data-chart-row="' + escAttr(item.chart_id) + '"' +
        (state.assetSelectMode ? ' tabindex="0" role="button" aria-label="选择版本 ' + escAttr(title) + ' ' + escAttr(_assetVersionLabel(item.version)) + '"' : '') + '>' +
        checkbox +
        '<span class="asset-version-tag' + (Number(item.version) > 0 ? ' opt' : '') + '" data-tip="' + escAttr(tip) + '">' +
          escHtml(_assetVersionLabel(item.version)) + '</span>' +
        '<span class="asset-type-tag">' + escHtml(type) + '</span>' +
        '<span class="asset-date">' + escHtml(_assetDate(item.created_at)) + '</span>' +
        actions +
      '</div>';
    });
    html += '</div></div>';
  });
  list.innerHTML = html;
  renderAssetBatchBar();
}

function renderAssetBatchBar() {
  const bar = document.getElementById('assetBatchBar');
  const manage = document.getElementById('assetManageBtn');
  const hasAssets = (state.assetVisibleIds || []).length > 0;
  if (manage) {
    manage.disabled = !hasAssets || state.assetsLoading;
    manage.classList.toggle('active', !!state.assetSelectMode);
    manage.setAttribute('aria-pressed', state.assetSelectMode ? 'true' : 'false');
    manage.setAttribute('data-tip', state.assetSelectMode ? '退出批量管理' : '批量管理当前对话资产');
    manage.setAttribute('aria-label', state.assetSelectMode ? '退出批量管理' : '批量管理当前对话资产');
  }
  if (!bar) return;
  if (!state.assetSelectMode) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }
  const n = (state.selectedAssetIds || []).length;
  const total = (state.assetVisibleIds || []).length;
  bar.style.display = 'flex';
  bar.innerHTML = '<span class="batch-count">已选 <strong>' + n + '</strong> / ' + total + '</span>' +
    '<button class="btn-sm" onclick="selectAllAssets()">全选</button>' +
    '<button class="btn-sm" onclick="selectNoneAssets()" ' + (n === 0 ? 'disabled' : '') + '>全不选</button>' +
    '<button class="btn-sm primary" onclick="batchExportAssets()" ' + (n === 0 ? 'disabled' : '') + '>导出</button>' +
    '<button class="btn-sm ghost" onclick="toggleAssetSelectMode()">取消</button>';
}

function toggleAssetSelectMode() {
  if (state.assetsLoading) return;
  state.assetSelectMode = !state.assetSelectMode;
  state.selectedAssetIds = [];
  renderAssets();
}

function _toggleAssetSelection(chartId) {
  if (!chartId) return;
  if (!state.selectedAssetIds) state.selectedAssetIds = [];
  const i = state.selectedAssetIds.indexOf(chartId);
  const on = i < 0;
  if (on) state.selectedAssetIds.push(chartId);
  else state.selectedAssetIds.splice(i, 1);
  const rows = document.querySelectorAll('#assetList .asset-version-row[data-chart-row]');
  for (const row of rows) {
    if (row.getAttribute('data-chart-row') !== chartId) continue;
    row.classList.toggle('selected', on);
    const cb = row.querySelector('.row-checkbox');
    if (cb) cb.checked = on;
    break;
  }
  renderAssetBatchBar();
}

function selectAllAssets() {
  state.selectedAssetIds = (state.assetVisibleIds || []).slice();
  renderAssets();
}

function selectNoneAssets() {
  state.selectedAssetIds = [];
  renderAssets();
}

function batchExportAssets() {
  const ids = (state.selectedAssetIds || []).slice();
  if (!ids.length) {
    window.app.showToast('未选择图表版本', 'info');
    return;
  }
  sendToRust('exportCharts', { chartIds: ids });
  window.app.showToast('正在导出 ' + ids.length + ' 个图表，请选择保存目录', 'info');
}

function openAssetChart(chartId, title, chartType) {
  if (!chartId) return;
  openChartViewer({
    chartId: chartId,
    title: title || chartId,
    chartType: chartType || '图表',
    path: assetChartPath(chartId),
    status: 'success',
  });
}

function optimizeAssetChart(chartId, title) {
  if (!chartId) return;
  setOptimizeTarget(chartId, title || chartId);
  window.app.showToast('已加入输入区，输入优化要求后发送', 'info');
}

(function initAssetListEvents() {
  const list = document.getElementById('assetList');
  if (!list) return;
  list.addEventListener('click', function (ev) {
    const btn = ev.target.closest ? ev.target.closest('[data-action]') : null;
    if (btn && btn.getAttribute('data-action') && btn.tagName === 'BUTTON') {
      const action = btn.getAttribute('data-action');
      const chartId = btn.getAttribute('data-chart') || '';
      const title = btn.getAttribute('data-title') || chartId;
      if (action === 'view') openAssetChart(chartId, title, btn.getAttribute('data-type') || '');
      else if (action === 'optimize') optimizeAssetChart(chartId, title);
      return;
    }
    const row = ev.target.closest ? ev.target.closest('.asset-version-row[data-chart-row]') : null;
    if (row && state.assetSelectMode) _toggleAssetSelection(row.getAttribute('data-chart-row'));
  });
  list.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const row = ev.target.closest ? ev.target.closest('.asset-version-row[data-chart-row]') : null;
    if (row && state.assetSelectMode && ev.target === row) {
      ev.preventDefault();
      _toggleAssetSelection(row.getAttribute('data-chart-row'));
    }
  });
})();
