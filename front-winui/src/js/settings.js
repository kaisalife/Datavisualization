// ===== 设置面板与数据库配置管理 =====
let editingDbId = null;
let editingModelId = null;

function renderSettings(cfg) {
  state.modelConfigs = cfg.modelConfigs || state.modelConfigs || [];
  document.getElementById('settingsBody').innerHTML =
    '<div class="settings-section"><div class="settings-section-title">模型配置管理</div>' +
      '<div class="db-list" id="modelList"></div>' +
      '<button class="db-add-btn" onclick="addModelConfigForm()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>添加模型配置</button>' +
      '<div class="form-group" style="margin-top:12px"><label class="form-label">MCP 提示词</label><input class="form-input" id="setMcp" value="' + escAttr(cfg.mcp || '') + '" placeholder="可选"></div>' +
      '<div class="form-group"><label class="form-label">技能提示词</label><input class="form-input" id="setSkill" value="' + escAttr(cfg.skill || '') + '" placeholder="可选"></div>' +
    '</div>' +
    '<div class="settings-section"><div class="settings-section-title">后端服务</div>' +
      '<div class="form-group"><label class="form-label">后端地址</label><input class="form-input" id="setBackend" value="' + escAttr(cfg.backend || '') + '" placeholder="http://localhost:5000"></div>' +
      '<div class="form-group"><label class="form-label">服务 API Key</label><input class="form-input" type="password" id="setApiKey" value="' + escAttr(cfg.apiKey || '') + '"></div>' +
    '</div>' +
    '<div class="settings-section"><div class="settings-section-title">数据库连接管理</div>' +
      '<div class="db-list" id="dbList"></div>' +
      '<button class="db-add-btn" onclick="addDbConfigForm()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>添加数据库连接</button>' +
    '</div>';
  state.dbConfigs = cfg.dbConfigs || state.dbConfigs;
  renderModelList();
  renderDbList();
}

function renderModelList() {
  const list = document.getElementById('modelList');
  if (!list) return;
  const configs = state.modelConfigs || [];
  if (configs.length === 0) {
    list.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;text-align:center;padding:12px">暂无模型配置</div>';
    return;
  }
  list.innerHTML = configs.map((m, idx) => {
    if (editingModelId === idx) {
      return '<div class="db-form">' +
        '<div class="form-group"><label class="form-label">配置名称</label><input class="form-input" id="emName" value="' + escAttr(m.name || '') + '"></div>' +
        '<div class="form-group"><label class="form-label">模型名称</label><input class="form-input" id="emType" value="' + escAttr(m.modelType || '') + '" placeholder="glm-4.5"></div>' +
        '<div class="form-group"><label class="form-label">API URL</label><input class="form-input" id="emUrl" value="' + escAttr(m.modelUrl || '') + '" placeholder="https://open.bigmodel.cn/api/paas/v4/"></div>' +
        '<div class="form-group"><label class="form-label">API Key</label><input class="form-input" type="password" id="emKey" value="' + escAttr(m.modelApiKey || '') + '" placeholder="sk-..."></div>' +
        '<div class="db-form-actions"><button class="btn btn-primary" style="padding:6px 16px;font-size:13px" onclick="saveModelEdit(' + idx + ')">保存</button><button class="btn btn-ghost" style="padding:6px 16px;font-size:13px" onclick="cancelModelEdit()">取消</button></div>' +
      '</div>';
    }
    return '<div class="db-config-card' + (m.enabled ? ' db-config-active' : '') + '">' +
      '<div class="db-config-header"><div class="db-config-name">' + escHtml(m.name || '未命名') + '</div>' +
      '<label style="display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer"><input type="radio" name="modelEnabled" ' + (m.enabled ? 'checked' : '') + ' onchange="enableModel(' + idx + ')">启用</label></div>' +
      '<div class="db-config-detail">' + escHtml(m.modelType || '-') + ' · ' + escHtml((m.modelUrl || '').replace(/^https?:\/\//, '')) + '</div>' +
      '<div class="db-config-actions"><button class="db-edit-btn" onclick="editModel(' + idx + ')">编辑</button><button class="db-del-btn" onclick="deleteModelConfig(' + idx + ')">删除</button></div>' +
    '</div>';
  }).join('');
}

function addModelConfigForm() {
  state.modelConfigs.push({ name: '新模型', modelType: '', modelUrl: '', modelApiKey: '', enabled: false });
  editingModelId = state.modelConfigs.length - 1;
  renderModelList();
}

function editModel(idx) { editingModelId = idx; renderModelList(); }
function cancelModelEdit() { editingModelId = null; renderModelList(); }

function saveModelEdit(idx) {
  const m = state.modelConfigs[idx];
  if (!m) return;
  m.name = document.getElementById('emName').value;
  m.modelType = document.getElementById('emType').value;
  m.modelUrl = document.getElementById('emUrl').value;
  m.modelApiKey = document.getElementById('emKey').value;
  editingModelId = null;
  renderModelList();
  window.app.showToast('模型配置已保存', 'success');
}

function deleteModelConfig(idx) {
  state.modelConfigs.splice(idx, 1);
  if (editingModelId === idx) editingModelId = null;
  renderModelList();
  window.app.showToast('已删除', 'info');
}

function enableModel(idx) {
  sendToRust('enableModel', { index: idx, modelConfigs: state.modelConfigs });
}

function renderDbList() {
  const list = document.getElementById('dbList');
  if (!list) return;
  if (!state.dbConfigs || state.dbConfigs.length === 0) {
    list.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;text-align:center;padding:12px">暂无数据库配置</div>';
    return;
  }
  list.innerHTML = state.dbConfigs.map((db, idx) => {
    const typeCls = 'db-type-' + (db.dbType || 'mysql').toLowerCase().replace(/\s/g, '');
    if (editingDbId === idx) {
      return '<div class="db-form">' +
        '<div class="form-group"><label class="form-label">连接名称</label><input class="form-input" id="edbName" value="' + escAttr(db.name) + '"></div>' +
        '<div class="form-row"><div class="form-group"><label class="form-label">类型</label><select class="form-select" id="edbType">' + ['MySQL','PostgreSQL','SQLite','SQL Server'].map(t => '<option ' + (db.dbType===t?'selected':'') + '>' + t + '</option>').join('') + '</select></div>' +
        '<div class="form-group"><label class="form-label">主机</label><input class="form-input" id="edbHost" value="' + escAttr(db.host) + '"></div>' +
        '<div class="form-group" style="max-width:90px"><label class="form-label">端口</label><input class="form-input" id="edbPort" value="' + escAttr(db.port) + '"></div></div>' +
        '<div class="form-row"><div class="form-group"><label class="form-label">用户名</label><input class="form-input" id="edbUser" value="' + escAttr(db.user) + '"></div>' +
        '<div class="form-group"><label class="form-label">密码</label><input class="form-input" type="password" id="edbPass" value="' + escAttr(db.password || '') + '"></div></div>' +
        '<div class="form-group"><label class="form-label">数据库</label><input class="form-input" id="edbDb" value="' + escAttr(db.database || '') + '"></div>' +
        '<div class="db-form-actions"><button class="btn btn-primary" style="padding:6px 16px;font-size:13px" onclick="saveDbEdit(' + idx + ')">保存</button><button class="btn btn-ghost" style="padding:6px 16px;font-size:13px" onclick="cancelDbEdit()">取消</button></div>' +
      '</div>';
    }
    return '<div class="db-config-card">' +
      '<div class="db-config-header"><div class="db-config-name">' + escHtml(db.name) + '</div><div class="db-config-type ' + typeCls + '">' + escHtml(db.dbType) + '</div></div>' +
      '<div class="db-config-detail">' + escHtml(db.host) + ':' + escHtml(db.port) + '/' + escHtml(db.database || '-') + '</div>' +
      '<div class="db-config-actions"><button class="db-edit-btn" onclick="editDb(' + idx + ')">编辑</button><button class="db-del-btn" onclick="deleteDbConfig(' + idx + ')">删除</button></div>' +
    '</div>';
  }).join('');
}

function addDbConfigForm() {
  state.dbConfigs.push({ name: '新连接', dbType: 'MySQL', host: 'localhost', port: '3306', user: 'root', password: '', database: '' });
  editingDbId = state.dbConfigs.length - 1;
  renderDbList();
}

function editDb(idx) { editingDbId = idx; renderDbList(); }
function cancelDbEdit() { editingDbId = null; renderDbList(); }

function saveDbEdit(idx) {
  const db = state.dbConfigs[idx];
  if (!db) return;
  db.name = document.getElementById('edbName').value;
  db.dbType = document.getElementById('edbType').value;
  db.host = document.getElementById('edbHost').value;
  db.port = document.getElementById('edbPort').value;
  db.user = document.getElementById('edbUser').value;
  db.password = document.getElementById('edbPass').value;
  db.database = document.getElementById('edbDb').value;
  editingDbId = null;
  renderDbList();
  window.app.showToast('数据库配置已保存', 'success');
}

function deleteDbConfig(idx) {
  state.dbConfigs.splice(idx, 1);
  if (editingDbId === idx) editingDbId = null;
  renderDbList();
  window.app.showToast('已删除', 'info');
}

function saveSettings() {
  const data = {
    modelConfigs: state.modelConfigs,
    mcp: document.getElementById('setMcp').value,
    skill: document.getElementById('setSkill').value,
    backend: document.getElementById('setBackend').value,
    apiKey: document.getElementById('setApiKey').value,
    dbConfigs: state.dbConfigs,
  };
  sendToRust('saveSettings', data);
}
