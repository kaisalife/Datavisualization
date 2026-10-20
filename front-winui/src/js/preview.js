// ===== 数据预览与导出 =====

// 输入框旁的「预览数据」入口：只对本地文件生效（数据库/API 需要走图表任务）
function requestDataPreview() {
  if (state.isGenerating) {
    window.app.showToast('正在生成图表，请完成后再预览数据', 'info');
    return;
  }
  const files = state.files.filter(f => typeof f === 'string');
  if (!files.length) {
    window.app.showToast('请先选择要预览的数据文件', 'info');
    return;
  }
  const hintInput = document.getElementById('prompt-input');
  const hint = hintInput ? hintInput.value.trim() : '';
  window.app.showToast('正在解析数据，图片/PDF 可能需要几十秒...', 'info');
  sendToRust('previewData', { files: files, hint: hint, multiTable: !!state.multiTable });
}

function closeDataPreview() {
  const modal = document.getElementById('dataPreviewModal');
  if (modal) modal.classList.remove('show');
}

function downloadDataExport(url, filename) {
  if (!url) {
    window.app.showToast('没有可下载的数据', 'info');
    return;
  }
  sendToRust('downloadDataExport', { url: url, filename: filename || 'export.csv' });
}

function _dpSafeFilename(name, ext) {
  const base = String(name == null ? 'export' : name).replace(/[\\/:*?"<>|]/g, '_').trim() || 'export';
  return base + (ext || '');
}

function _dpPreviewTable(profile) {
  const schema = Array.isArray(profile.schema) ? profile.schema : [];
  const rows = Array.isArray(profile.preview) ? profile.preview : [];
  let columns = schema.map(c => c.name);
  if (!columns.length && rows.length) columns = Object.keys(rows[0]);
  if (!columns.length) return '<div class="dp-muted">暂无预览数据</div>';

  const head = '<tr>' + columns.map(c => '<th>' + escHtml(c) + '</th>').join('') + '</tr>';
  const body = rows.map(row => {
    return '<tr>' + columns.map(c => {
      const value = row && Object.prototype.hasOwnProperty.call(row, c) ? row[c] : '';
      return '<td>' + escHtml(value == null ? '' : value) + '</td>';
    }).join('') + '</tr>';
  }).join('');
  return '<div class="dp-table-wrap"><table class="dp-table"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
}

function _dpSeriesList(profile, sessionId) {
  const exports = Array.isArray(profile.exports) ? profile.exports : [];
  const rows = exports.map(item => {
    const name = item.name || item.series_id || 'series';
    const axis = item.axis_kind ? ' · ' + escHtml(item.axis_kind) : '';
    const filename = _dpSafeFilename(name, '.csv');
    const button = item.csv_url
      ? '<button class="btn btn-ghost dp-download" data-url="' + escAttr(item.csv_url) + '" data-filename="' + escAttr(filename) + '" onclick="downloadDataExport(this.dataset.url,this.dataset.filename)">下载 CSV</button>'
      : '';
    return '<div class="dp-item"><div><div class="dp-item-main">' + escHtml(name) + '</div>' +
      '<div class="dp-item-sub">' + escHtml(item.series_id || '') + axis + '</div></div>' + button + '</div>';
  }).join('');
  if (!rows) return '<div class="dp-muted">没有可导出的 series</div>';

  const zipUrl = sessionId
    ? '/api/data-profile/export?session_id=' + encodeURIComponent(sessionId)
    : '';
  const zipButton = zipUrl
    ? '<button class="btn btn-ghost dp-download" data-url="' + escAttr(zipUrl) + '" data-filename="' + escAttr(_dpSafeFilename('series_' + sessionId, '.zip')) + '" onclick="downloadDataExport(this.dataset.url,this.dataset.filename)">全部导出 ZIP</button>'
    : '';
  return '<div class="dp-list">' + rows + '</div>' + (zipButton ? '<div class="dp-actions">' + zipButton + '</div>' : '');
}

function _dpRawTableList(profile, sessionId) {
  const rawTables = Array.isArray(profile.raw_tables) ? profile.raw_tables : [];
  const rows = rawTables.map(item => {
    const name = item.name || ('raw_' + item.index);
    const columns = Array.isArray(item.columns) ? item.columns.join('、') : '';
    const meta = (item.rows || 0) + ' 行' + (columns ? ' · ' + columns : '');
    const filename = _dpSafeFilename(name, '.csv');
    const button = item.csv_url
      ? '<button class="btn btn-ghost dp-download" data-url="' + escAttr(item.csv_url) + '" data-filename="' + escAttr(filename) + '" onclick="downloadDataExport(this.dataset.url,this.dataset.filename)">下载 CSV</button>'
      : '';
    return '<div class="dp-item"><div><div class="dp-item-main">' + escHtml(name) + '</div>' +
      '<div class="dp-item-sub">' + escHtml(meta) + '</div></div>' + button + '</div>';
  }).join('');
  if (!rows) return '<div class="dp-muted">没有原始表导出（图表任务默认不保存原始表）</div>';

  const zipUrl = sessionId
    ? '/api/data-profile/export?session_id=' + encodeURIComponent(sessionId) + '&raw=all'
    : '';
  const zipButton = zipUrl
    ? '<button class="btn btn-ghost dp-download" data-url="' + escAttr(zipUrl) + '" data-filename="' + escAttr(_dpSafeFilename('raw_tables_' + sessionId, '.zip')) + '" onclick="downloadDataExport(this.dataset.url,this.dataset.filename)">全部导出 ZIP</button>'
    : '';
  return '<div class="dp-list">' + rows + '</div>' + (zipButton ? '<div class="dp-actions">' + zipButton + '</div>' : '');
}

function showDataPreview(payload) {
  let parsed;
  try {
    parsed = typeof payload === 'string' ? JSON.parse(payload) : payload;
  } catch (e) {
    window.app.showToast('数据预览解析失败', 'error');
    return;
  }
  const profile = (parsed && parsed.profile) ? parsed.profile : (parsed || {});
  const sessionId = profile.session_id || '';
  const title = document.getElementById('dataPreviewTitle');
  const body = document.getElementById('dataPreviewBody');
  if (!title || !body) return;

  title.textContent = '数据预览 · ' + (profile.table_name || '数据集');

  const schema = Array.isArray(profile.schema) ? profile.schema : [];
  const schemaHtml = schema.map(col => {
    const role = col.semantic_role ? ' · ' + escHtml(col.semantic_role) : '';
    return '<span class="dp-schema-chip">' + escHtml(col.name) + '<em>' + escHtml(col.type || '') + role + '</em></span>';
  }).join('');

  const related = Array.isArray(profile.related_tables) ? profile.related_tables.length : 0;
  const degraded = profile.degraded
    ? '<div class="dp-warning">解析降级：' + escHtml(profile.degraded_reason || profile.degraded) + '</div>'
    : '';

  body.innerHTML =
    '<div class="dp-summary">' +
      '<div class="dp-summary-main">' + escHtml(profile.table_name || '数据集') + '</div>' +
      '<div class="dp-summary-sub">' + escHtml(profile.source_kind || 'file') + ' · ' +
        (profile.row_count || 0) + ' 行 · ' + schema.length + ' 列' +
        (related ? ' · ' + related + ' 个关联表' : '') + '</div>' +
      degraded +
    '</div>' +
    '<div class="dp-section"><div class="dp-section-title">字段</div>' +
      '<div class="dp-schema">' + (schemaHtml || '<span class="dp-muted">无字段信息</span>') + '</div></div>' +
    '<div class="dp-section"><div class="dp-section-title">数据预览（前 ' + ((profile.preview || []).length) + ' 行）</div>' +
      _dpPreviewTable(profile) + '</div>' +
    '<div class="dp-section"><div class="dp-section-title">语义 Series</div>' +
      _dpSeriesList(profile, sessionId) + '</div>' +
    '<div class="dp-section"><div class="dp-section-title">原始表（抽表 / 归一化后）</div>' +
      _dpRawTableList(profile, sessionId) + '</div>';

  document.getElementById('dataPreviewModal').classList.add('show');
}

window.app.showDataPreview = showDataPreview;
