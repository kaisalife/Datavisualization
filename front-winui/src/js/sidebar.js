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
  else renderFileTree();
}

// ===== 对话列表 =====
function renderConversations(filter) {
  let list = state.conversations || [];
  const container = document.getElementById('convList');
  if (list.length === 0) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-secondary);padding:20px;font-size:12px">暂无历史记录</div>';
    return;
  }
  if (filter) list = list.filter(c => (c.prompt || '').includes(filter));
  let html = '<div class="conv-section-label">最近</div>';
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
  return '<div class="conversation-item" onclick="loadConv(\'' + escAttr(c.id) + '\')">' +
    '<div class="conv-icon">' + icon + '</div>' +
    '<div class="conv-content">' +
      '<div class="conv-title">' + escHtml(c.prompt || '(无提示词)') + '</div>' +
      '<div class="conv-meta"><span>' + date + '</span><span class="conv-status ' + stCls + '">' + st + '</span></div>' +
      '<div class="conv-actions">' +
        '<button class="conv-action-btn" onclick="event.stopPropagation();loadConv(\'' + escAttr(c.id) + '\')">查看</button>' +
        '<button class="conv-action-btn" onclick="event.stopPropagation();editConvPrompt(\'' + escAttr(c.id) + '\',\'' + escAttr(c.prompt || '') + '\')">改提示词</button>' +
        '<button class="conv-action-btn del" onclick="event.stopPropagation();deleteConv(\'' + escAttr(c.id) + '\')">删除</button>' +
      '</div>' +
    '</div></div>';
}

function filterConversations(v) { renderConversations(v); }
function loadConv(id) { sendToRust('viewDetail', { conversationId: id }); }
function deleteConv(id) { sendToRust('deleteConversation', { conversationId: id }); }
function editConvPrompt(id, oldPrompt) {
  const np = prompt('修改提示词后可重新提交:', oldPrompt || '');
  if (np !== null && np.trim()) sendToRust('updatePrompt', { conversationId: id, prompt: np });
}

// ===== 文件列表 =====
function renderFileTree(filter) {
  const container = document.getElementById('fileTree');
  if (!state.fileList || state.fileList.length === 0) {
    container.innerHTML = '<div class="files-empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><div>打开项目文件夹<br>浏览数据文件</div></div>';
    return;
  }
  let files = state.fileList;
  if (filter) files = files.filter(f => (f.name || '').toLowerCase().includes(filter.toLowerCase()));
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
    html += '<div class="file-node" onclick="' + (canAdd ? 'event.stopPropagation();addFileFromExplorer(\'' + escAttr(f.path) + '\')' : '') + '">' +
      '<span style="width:12px"></span><span class="file-icon">' + iconFor(f.name) + '</span>' +
      '<span class="file-name">' + escHtml(f.name) + '</span>' +
      (canAdd ? '<span class="add-btn" title="添加到对话"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></span>' : '') +
    '</div>';
  });
  container.innerHTML = html;
}

function filterFiles(v) { renderFileTree(v); }

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
    const remove = document.createElement('span');
    remove.className = 'remove';
    remove.textContent = '✕';
    remove.onclick = function() { state.files.splice(idx, 1); renderFileChips(); };
    chip.appendChild(icon);
    chip.appendChild(nameEl);
    chip.appendChild(remove);
    container.appendChild(chip);
  });
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
