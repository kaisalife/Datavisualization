// ===== Header / Sidebar 切换 =====
function switchHeaderMode(mode) {
  sendToRust('switchMode', { mode: mode });
}

function switchSidebarTab(tab, el) {
  state.sidebarTab = tab;
  document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + tab).classList.add('active');
  if (tab === 'conversations') renderConversations();
  else if (tab === 'assets') {
    renderAssets();
    loadConversationAssets();
  } else renderFileTree();
}

// ===== 对话列表 =====
function renderConversations(filter) {
  let list = state.conversations || [];
  const container = document.getElementById('convList');
  if (list.length === 0) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-secondary);padding:20px;font-size:12px">暂无历史记录</div>';
    return;
  }
  if (filter) {
    const q = String(filter).toLowerCase();
    list = list.filter(c => (c.prompt || '').toLowerCase().includes(q));
  }
  let html = '';
  // 多选模式操作栏
  if (state.selectMode) {
    const n = (state.selectedIds || []).length;
    html += '<div class="select-bar"><span>已选 ' + n + ' 个</span>' +
      '<button class="btn-sm" onclick="selectAllConvs()">全选</button>' +
      '<button class="btn-sm danger" onclick="batchDeleteSelected()">删除选中</button>' +
      '<button class="btn-sm" onclick="exitSelectMode()">取消</button></div>';
  }
  html += '<div class="conv-section-label">最近</div>';
  html += list.slice(0, Math.min(2, list.length)).map(c => convItemHtml(c)).join('');
  if (list.length > 2) {
    html += '<div class="conv-section-label">更早</div>';
    html += list.slice(2).map(c => convItemHtml(c)).join('');
  }
  container.innerHTML = html;
}

function convItemHtml(c) {
  const st = (c.status || 'pending').toLowerCase();
  const stCls = ['success','failed','running','pending'].includes(st) ? st : 'pending';
  const icon = '📈';
  const date = (c.createdAt || '').substring(0, 16);
  const sel = state.selectMode;
  const checked = sel && state.selectedIds && state.selectedIds.indexOf(c.id) >= 0;
  const checkbox = sel ? '<input type="checkbox" class="conv-checkbox" data-action="toggle" tabindex="-1" ' + (checked ? 'checked' : '') + '>' : '';
  const actions = sel ? '' :
      '<div class="conv-actions">' +
        '<button class="conv-action-btn" data-action="view">查看</button>' +
        '<button class="conv-action-btn" data-action="edit">改提示词</button>' +
        '<button class="conv-action-btn del" data-action="delete">删除</button>' +
      '</div>';
  return '<div class="conversation-item' + (checked ? ' selected' : '') + '" data-id="' + escAttr(c.id) + '" data-prompt="' + escAttr(c.prompt || '') + '" data-action="open" tabindex="0" role="button">' +
    checkbox +
    '<div class="conv-icon">' + icon + '</div>' +
    '<div class="conv-content">' +
      '<div class="conv-title">' + escHtml(c.prompt || '(无提示词)') + '</div>' +
      '<div class="conv-meta"><span>' + date + '</span><span class="conv-status ' + stCls + '">' + st + '</span></div>' +
      actions +
    '</div></div>';
}

// 事件委托：列表项不再内联 onclick，既少一次 HTML 解析，也避免 id/提示词拼进 JS 字符串
// （历史上靠 escAttr 防注入，这里彻底移除了这条注入面）。
function _onConvListClick(e) {
  const item = e.target.closest ? e.target.closest('.conversation-item') : null;
  if (!item) return;
  const actionEl = e.target.closest ? e.target.closest('[data-action]') : null;
  const action = actionEl ? actionEl.getAttribute('data-action') : 'open';
  const id = item.getAttribute('data-id');
  if (!id) return;
  if (state.selectMode) {
    if (action === 'open' || action === 'toggle') toggleSelect(id);
    return;
  }
  if (action === 'view') loadConv(id);
  else if (action === 'edit') editConvPrompt(id, item.getAttribute('data-prompt') || '');
  else if (action === 'delete') deleteConv(id);
  else loadConv(id);
}

(function initConvListEvents() {
  const container = document.getElementById('convList');
  if (!container) return;
  container.addEventListener('click', _onConvListClick);
  // 键盘可达：行本身聚焦时 Enter/Space 等同于点击（嵌套按钮由其自身处理）
  container.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const item = e.target.closest ? e.target.closest('.conversation-item') : null;
    if (item && e.target === item) {
      e.preventDefault();
      item.click();
    }
  });
})();

function _updateSelectBarCount() {
  const label = document.querySelector('#convList .select-bar span');
  if (label) label.textContent = '已选 ' + ((state.selectedIds || []).length) + ' 个';
}

// 搜索框防抖：历史对话较多时逐字重建整列表会卡输入
const filterConversations = debounce(function (v) { renderConversations(v); }, 120);
function loadConv(id) { sendToRust('viewDetail', { conversationId: id }); }
function deleteConv(id) { sendToRust('deleteConversation', { conversationId: id }); }
function editConvPrompt(id, oldPrompt) {
  const np = prompt('修改提示词后可重新提交:', oldPrompt || '');
  if (np !== null && np.trim()) sendToRust('updatePrompt', { conversationId: id, prompt: np });
}

// ===== 对话数量清理提醒 =====
function checkCleanupReminder() {
  const total = state.total || 0;
  hideCleanupBanner();
  if (total > 100) {
    showCleanupModal(total);
  } else if (total > 30 && !localStorage.getItem('hideCleanupReminder')) {
    showCleanupBanner(total);
  }
}

function showCleanupBanner(total) {
  let el = document.getElementById('cleanupBanner');
  if (!el) {
    el = document.createElement('div');
    el.id = 'cleanupBanner';
    el.className = 'cleanup-banner';
    const panel = document.getElementById('panel-conversations');
    panel.insertBefore(el, panel.firstChild);
  }
  el.innerHTML = '<span>📋 历史对话较多(' + total + '个)，建议清理</span>' +
    '<button class="banner-btn" onclick="enterSelectMode()">批量清理</button>' +
    '<button class="banner-btn" onclick="dismissCleanupReminder()">不再提醒</button>';
}

function hideCleanupBanner() {
  const el = document.getElementById('cleanupBanner');
  if (el) el.remove();
}

function dismissCleanupReminder() {
  localStorage.setItem('hideCleanupReminder', '1');
  hideCleanupBanner();
  window.app.showToast('已关闭提醒（超过100仍会提示）', 'info');
}

function showCleanupModal(total) {
  let el = document.getElementById('cleanupModal');
  if (!el) {
    el = document.createElement('div');
    el.id = 'cleanupModal';
    el.className = 'modal-overlay';
    el.innerHTML = '<div class="modal-dialog">' +
      '<div class="modal-title">⚠️ 历史对话超过 100 个</div>' +
      '<div class="modal-body">当前共 ' + total + ' 个对话，过多可能影响性能。请选择清理方式：</div>' +
      '<div class="modal-actions">' +
        '<button class="btn btn-primary" onclick="enterSelectMode()">手动选择删除</button>' +
        '<button class="btn" onclick="deleteOldest(30)">自动清理最老30个</button>' +
        '<button class="btn" onclick="closeCleanupModal()">稍后</button>' +
      '</div></div>';
    document.body.appendChild(el);
  } else {
    el.querySelector('.modal-body').textContent = '当前共 ' + total + ' 个对话，过多可能影响性能。请选择清理方式：';
  }
  el.style.display = 'flex';
}

function closeCleanupModal() {
  const el = document.getElementById('cleanupModal');
  if (el) el.style.display = 'none';
}

function deleteOldest(count) {
  closeCleanupModal();
  sendToRust('deleteOldest', { count: count });
}

// ===== 多选模式 =====
function enterSelectMode() {
  state.selectMode = true;
  state.selectedIds = [];
  closeCleanupModal();
  hideCleanupBanner();
  renderConversations();
}

function exitSelectMode() {
  state.selectMode = false;
  state.selectedIds = [];
  renderConversations();
}

function toggleSelect(id) {
  if (!state.selectedIds) state.selectedIds = [];
  const i = state.selectedIds.indexOf(id);
  const on = i < 0;
  if (on) state.selectedIds.push(id);
  else state.selectedIds.splice(i, 1);
  // 只更新这一行，避免整列表重建（几十上百条时每点一次都重排）
  const row = _findConvRow(id);
  if (row) {
    row.classList.toggle('selected', on);
    const cb = row.querySelector('.conv-checkbox');
    if (cb) cb.checked = on;
  }
  _updateSelectBarCount();
}

function _findConvRow(id) {
  const rows = document.querySelectorAll('#convList .conversation-item');
  for (const row of rows) {
    if (row.getAttribute('data-id') === id) return row;
  }
  return null;
}

function selectAllConvs() {
  state.selectedIds = (state.conversations || []).map(c => c.id);
  renderConversations();
}

function batchDeleteSelected() {
  if (!state.selectedIds || state.selectedIds.length === 0) {
    window.app.showToast('未选择对话', 'info');
    return;
  }
  sendToRust('batchDelete', { ids: state.selectedIds });
  exitSelectMode();
}

// ===== 文件列表 =====
function renderFileTree(filter) {
  const container = document.getElementById('fileTree');
  if (!state.fileList || state.fileList.length === 0) {
    container.innerHTML = '<div class="files-empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><div>打开项目文件夹<br>浏览数据文件</div></div>';
    return;
  }
  let files = state.fileList;
  if (filter) {
    const q = String(filter).toLowerCase();
    files = files.filter(f => (f.name || '').toLowerCase().includes(q));
  }
  const dataExts = ['.csv','.xlsx','.xls','.json','.pdf','.parquet','.txt','.xml','.py'];
  function iconFor(name) {
    const ext = name.substring(name.lastIndexOf('.')).toLowerCase();
    return {'.csv':'📊','.xlsx':'📗','.xls':'📗','.json':'📋','.pdf':'📄','.parquet':'🗃️','.py':'🐍','.txt':'📝'}[ext] || '📄';
  }
  function isData(name) {
    const ext = name.substring(name.lastIndexOf('.')).toLowerCase();
    return dataExts.includes(ext);
  }
  let html = '';
  files.forEach(f => {
    const canAdd = isData(f.name);
    const addLabel = '添加 ' + f.name + ' 到对话';
    html += '<div class="file-node"' + (canAdd ? ' data-add-path="' + escAttr(f.path) + '" tabindex="0" role="button" aria-label="' + escAttr(addLabel) + '"' : '') + '>' +
      '<span style="width:12px"></span><span class="file-icon">' + iconFor(f.name) + '</span>' +
      '<span class="file-name">' + escHtml(f.name) + '</span>' +
      (canAdd ? '<span class="add-btn" data-tip="添加到对话" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></span>' : '') +
    '</div>';
  });
  container.innerHTML = html;
}

// 文件树同样走事件委托，路径不再拼进内联 onclick
function _onFileTreeClick(e) {
  const node = e.target.closest ? e.target.closest('.file-node[data-add-path]') : null;
  if (!node) return;
  addFileFromExplorer(node.getAttribute('data-add-path'));
}

(function initFileTreeEvents() {
  const container = document.getElementById('fileTree');
  if (!container) return;
  container.addEventListener('click', _onFileTreeClick);
  container.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const node = e.target.closest ? e.target.closest('.file-node[data-add-path]') : null;
    if (node && e.target === node) {
      e.preventDefault();
      node.click();
    }
  });
})();

const filterFiles = debounce(function (v) { renderFileTree(v); }, 120);

function closeProject() {
  state.projectName = null;
  state.fileList = [];
  document.getElementById('projectInfo').style.display = 'none';
  document.getElementById('fileSearchBox').style.display = 'none';
  renderFileTree();
}

function addFileFromExplorer(path) {
  if (state.files.indexOf(path) < 0) {
    state.files.push(path);
    renderFileChips();
    window.app.showToast('已添加文件', 'success');
  } else {
    window.app.showToast('文件已在对话中', 'info');
  }
}

// ===== 文件标签 =====
function renderFileChips() {
  const container = document.getElementById('fileChips');
  container.innerHTML = '';
  state.files.forEach((item, idx) => {
    const isObj = typeof item === 'object';
    const name = isObj ? item.name : (item.split(/[\\/]/).pop() || item);
    const isDb = isObj && item.isDb;
    const chip = document.createElement('div');
    chip.className = 'file-chip';
    const icon = document.createElement('span');
    icon.textContent = isDb ? '🗄️' : '📄';
    const nameEl = document.createElement('span');
    nameEl.className = 'chip-name';
    nameEl.textContent = name;
    nameEl.title = isObj ? name : item;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove';
    remove.textContent = '✕';
    remove.setAttribute('data-tip', '从对话移除');
    remove.setAttribute('aria-label', '移除文件 ' + name);
    remove.onclick = function() { state.files.splice(idx, 1); renderFileChips(); };
    chip.appendChild(icon);
    chip.appendChild(nameEl);
    chip.appendChild(remove);
    container.appendChild(chip);
  });
  if (state.apiConfig) {
    const chip = document.createElement('div');
    chip.className = 'file-chip';
    const icon = document.createElement('span');
    icon.textContent = '🌐';
    const nameEl = document.createElement('span');
    nameEl.className = 'chip-name';
    nameEl.textContent = state.apiConfig.url.substring(0, 30);
    nameEl.title = state.apiConfig.url;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove';
    remove.textContent = '✕';
    remove.setAttribute('data-tip', '移除 API 数据源');
    remove.setAttribute('aria-label', '移除 API 数据源');
    remove.onclick = function() { state.apiConfig = null; renderFileChips(); };
    chip.appendChild(icon);
    chip.appendChild(nameEl);
    chip.appendChild(remove);
    container.appendChild(chip);
  }
}

// ===== 数据库选择弹窗 =====
function showDbSelector() {
  const body = document.getElementById('dbSelectorBody');
  if (!state.dbConfigs || state.dbConfigs.length === 0) {
    body.innerHTML = '<div style="text-align:center;color:var(--text-secondary);padding:20px">还没有数据库配置<br><button class="btn btn-primary" style="margin-top:12px" onclick="document.getElementById(\'dbSelectorModal\').classList.remove(\'show\');sendToRust(\'toggleSettings\',{})">去设置添加</button></div>';
  } else {
    body.innerHTML = state.dbConfigs.map(db => {
      const typeCls = 'db-type-' + (db.dbType || 'mysql').toLowerCase().replace(/\s/g, '');
      return '<div class="db-config-card" onclick="selectDb(\'' + escAttr(db.name) + '\')" style="cursor:pointer;margin-bottom:8px">' +
        '<div class="db-config-header"><div class="db-config-name">' + escHtml(db.name) + '</div><div class="db-config-type ' + typeCls + '">' + escHtml(db.dbType) + '</div></div>' +
        '<div class="db-config-detail">' + escHtml(db.host) + ':' + escHtml(db.port) + '/' + escHtml(db.database || '-') + '</div>' +
      '</div>';
    }).join('') + '<button class="db-add-btn" onclick="document.getElementById(\'dbSelectorModal\').classList.remove(\'show\');sendToRust(\'toggleSettings\',{})"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>添加新连接</button>';
  }
  document.getElementById('dbSelectorModal').classList.add('show');
}

function selectDb(name) {
  document.getElementById('dbSelectorModal').classList.remove('show');
  const db = state.dbConfigs.find(d => d.name === name);
  if (!db) return;
  state.selectedDb = name;
  state.files.push({ name: db.name, isDb: true });
  renderFileChips();
  window.app.showToast('已选择数据库: ' + db.name, 'success');
  sendToRust('selectDb', { name: name });
}

// ===== API 数据源配置 =====
function showApiConfig() {
  document.getElementById('apiConfigModal').classList.add('show');
}

function saveApiConfig() {
  const url = document.getElementById('apiUrl').value.trim();
  if (!url) { window.app.showToast('请输入 URL', 'error'); return; }
  const method = document.getElementById('apiMethod').value;
  let headers = null, params = null;
  try { headers = JSON.parse(document.getElementById('apiHeaders').value || 'null'); }
  catch(e) { window.app.showToast('请求头 JSON 格式错误', 'error'); return; }
  try { params = JSON.parse(document.getElementById('apiParams').value || 'null'); }
  catch(e) { window.app.showToast('查询参数 JSON 格式错误', 'error'); return; }
  const body = document.getElementById('apiBody').value.trim() || null;
  state.apiConfig = { url, method, headers, params, body };
  state.selectedDb = null;
  state.files = [];
  renderFileChips();
  document.getElementById('apiConfigModal').classList.remove('show');
  window.app.showToast('已配置 API 数据源', 'success');
}
