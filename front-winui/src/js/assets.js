// ===== 当前对话图表资产（列表 / 版本链 / 二次优化入口） =====
// 数据来自后端 /api/conversation-assets/<conversation_id>：
// 同一张图的 v0/v1/v2… 会通过 root_chart_id 归到一组。

function resetAssets() {
  state.conversationId = null;
  state.assets = [];
  state.assetsLoading = false;
  renderAssets();
}

function setCurrentConversation(conversationId) {
  state.conversationId = conversationId || null;
}

function loadConversationAssets() {
  if (!state.conversationId) {
    state.assets = [];
    state.assetsLoading = false;
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
  if (countEl) countEl.textContent = String(assets.length);
  if (tabCount) {
    tabCount.textContent = String(assets.length);
    tabCount.style.display = assets.length > 0 ? 'inline-flex' : 'none';
  }

  if (!state.conversationId) {
    list.innerHTML = '<div class="asset-empty"><div class="asset-empty-icon">🗂️</div>' +
      '<div>当前对话还没有生成图表</div>' +
      '<div class="asset-empty-sub">发送需求后，生成的图表和优化版本会出现在这里</div></div>';
    return;
  }

  if (state.assetsLoading) {
    list.innerHTML = '<div class="asset-empty"><div class="asset-empty-icon">⏳</div>' +
      '<div>正在加载图表资产…</div></div>';
    return;
  }

  if (assets.length === 0) {
    list.innerHTML = '<div class="asset-empty"><div class="asset-empty-icon">🗂️</div>' +
      '<div>这个对话还没有图表资产</div>' +
      '<div class="asset-empty-sub">任务完成后点击右上角刷新，或重新发送需求</div></div>';
    return;
  }

  const groups = _assetGroups();
  let html = '<div class="asset-summary">' + groups.length + ' 张图 · ' + assets.length + ' 个版本</div>';
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
      const tip = item.optimize_prompt
        ? '优化指令：' + item.optimize_prompt
        : (Number(item.version) > 0 ? '二次优化版本' : '原始生成版本');
      html += '<div class="asset-version-row">' +
        '<span class="asset-version-tag' + (Number(item.version) > 0 ? ' opt' : '') + '" data-tip="' + escAttr(tip) + '">' +
          escHtml(_assetVersionLabel(item.version)) + '</span>' +
        '<span class="asset-type-tag">' + escHtml(type) + '</span>' +
        '<span class="asset-date">' + escHtml(_assetDate(item.created_at)) + '</span>' +
        '<span class="asset-version-actions">' +
          '<button type="button" class="asset-action-btn" data-action="view" data-chart="' + escAttr(item.chart_id) + '" data-title="' + escAttr(title) + '" data-type="' + escAttr(type) + '" data-tip="全屏查看这张图" aria-label="查看图表">查看</button>' +
          '<button type="button" class="asset-action-btn primary" data-action="optimize" data-chart="' + escAttr(item.chart_id) + '" data-title="' + escAttr(title) + '" data-tip="把这张图加入输入区，发送修改要求（只重新渲染这张图）" aria-label="优化这张图表">优化</button>' +
        '</span>' +
      '</div>';
    });
    html += '</div></div>';
  });
  list.innerHTML = html;
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
    if (!btn) return;
    const action = btn.getAttribute('data-action');
    const chartId = btn.getAttribute('data-chart') || '';
    const title = btn.getAttribute('data-title') || chartId;
    if (action === 'view') openAssetChart(chartId, title, btn.getAttribute('data-type') || '');
    else if (action === 'optimize') optimizeAssetChart(chartId, title);
  });
})();
