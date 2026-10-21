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
  sendToRust('syncModelConfigs', { modelConfigs: state.modelConfigs });
}

function deleteModelConfig(idx) {
  state.modelConfigs.splice(idx, 1);
  if (editingModelId === idx) editingModelId = null;
  renderModelList();
  window.app.showToast('已删除', 'info');
  sendToRust('syncModelConfigs', { modelConfigs: state.modelConfigs });
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
    const scope = (db.query || '').trim()
      ? '自定义 SQL'
      : ((db.tables || '').trim() ? '表: ' + db.tables.trim() : '全部表');
    if (editingDbId === idx) {
      return '<div class="db-form">' +
        '<div class="form-group"><label class="form-label">连接名称</label><input class="form-input" id="edbName" value="' + escAttr(db.name) + '"></div>' +
        '<div class="form-row"><div class="form-group"><label class="form-label">类型</label><select class="form-select" id="edbType">' + dbTypeOptions(db.dbType) + '</select></div>' +
        '<div class="form-group"><label class="form-label">主机</label><input class="form-input" id="edbHost" value="' + escAttr(db.host) + '"></div>' +
        '<div class="form-group" style="max-width:90px"><label class="form-label">端口</label><input class="form-input" id="edbPort" value="' + escAttr(db.port) + '"></div></div>' +
        '<div class="form-row"><div class="form-group"><label class="form-label">用户名</label><input class="form-input" id="edbUser" value="' + escAttr(db.user) + '"></div>' +
        '<div class="form-group"><label class="form-label">密码</label><input class="form-input" type="password" id="edbPass" value="' + escAttr(db.password || '') + '"></div></div>' +
        '<div class="form-group"><label class="form-label">数据库</label><input class="form-input" id="edbDb" value="' + escAttr(db.database || '') + '"></div>' +
        '<div class="form-group"><label class="form-label">表名（可选，逗号分隔）</label><input class="form-input" id="edbTables" value="' + escAttr(db.tables || '') + '" placeholder="留空读取全部表，如 sales,users" oninput="syncDbTableChips()"></div>' +
        '<div class="form-group"><label class="form-label">自定义 SQL（可选，优先于表名）</label><textarea class="form-input" id="edbQuery" rows="3" placeholder="SELECT * FROM sales WHERE ...">' + escHtml(db.query || '') + '</textarea></div>' +
        '<div class="db-form-actions"><button class="btn btn-primary" style="padding:6px 16px;font-size:13px" onclick="saveDbEdit(' + idx + ')">保存</button>' +
          '<button class="btn btn-ghost" style="padding:6px 16px;font-size:13px" onclick="testDbConnection()">测试连接</button>' +
          '<button class="btn btn-ghost" style="padding:6px 16px;font-size:13px" onclick="cancelDbEdit()">取消</button></div>' +
        '<div class="db-test-result" id="edbTestResult"></div>' +
      '</div>';
    }
    return '<div class="db-config-card">' +
      '<div class="db-config-header"><div class="db-config-name">' + escHtml(db.name) + '</div><div class="db-config-type ' + typeCls + '">' + escHtml(db.dbType) + '</div></div>' +
      '<div class="db-config-detail">' + escHtml(db.host) + ':' + escHtml(db.port) + '/' + escHtml(db.database || '-') + '</div>' +
      '<div class="db-config-detail">' + escHtml(scope) + '</div>' +
      '<div class="db-config-actions"><button class="db-edit-btn" onclick="editDb(' + idx + ')">编辑</button><button class="db-del-btn" onclick="deleteDbConfig(' + idx + ')">删除</button></div>' +
    '</div>';
  }).join('');
}

function addDbConfigForm() {
  state.dbConfigs.push({ name: '新连接', dbType: 'MySQL', host: 'localhost', port: '3306', user: 'root', password: '', database: '', tables: '', query: '' });
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
  db.tables = document.getElementById('edbTables').value;
  db.query = document.getElementById('edbQuery').value;
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

// ===== 数据库连接测试 =====

// 新增连接只提供后端支持的方言；历史配置里的 SQL Server 仍保留原值，
// 避免编辑一次就被静默改成 MySQL（后端会以 400 明确拒绝）。
function dbTypeOptions(current) {
  const types = ['MySQL', 'PostgreSQL', 'SQLite'];
  if (current && types.indexOf(current) < 0) types.push(current);
  return types.map(t => {
    const label = t === 'SQL Server' ? 'SQL Server（暂不支持）' : t;
    return '<option value="' + escAttr(t) + '"' + (current === t ? ' selected' : '') + '>' + escHtml(label) + '</option>';
  }).join('');
}

function testDbConnection() {
  const box = document.getElementById('edbTestResult');
  if (!document.getElementById('edbHost')) return;
  if (box) box.innerHTML = '<span class="db-test-pending">正在连接...</span>';
  sendToRust('testDbConfig', {
    name: (document.getElementById('edbName') || {}).value || '',
    dbType: (document.getElementById('edbType') || {}).value || 'MySQL',
    host: (document.getElementById('edbHost') || {}).value || '',
    port: (document.getElementById('edbPort') || {}).value || '',
    user: (document.getElementById('edbUser') || {}).value || '',
    password: (document.getElementById('edbPass') || {}).value || '',
    database: (document.getElementById('edbDb') || {}).value || '',
  });
}

// 把后端返回的表列表渲染到表单里；点击表名可加入/移出「表名」输入框
function renderDbTablesResult(jsonStr) {
  let result;
  try { result = JSON.parse(jsonStr); } catch (e) { return; }
  const box = document.getElementById('edbTestResult');
  if (!box) {
    window.app.showToast('数据库连接成功', 'success');
    return;
  }
  const tables = Array.isArray(result.tables) ? result.tables : [];
  let html = '<div class="db-test-ok">连接成功' +
    (result.db_type ? ' · ' + escHtml(result.db_type) : '') +
    ' · ' + tables.length + ' 张表</div>';
  if (tables.length) {
    html += '<div class="db-table-chips">' + tables.map(t =>
      '<button type="button" class="db-table-chip" data-table="' + escAttr(t) + '" title="点击加入表名" onclick="toggleDbTable(this)">' + escHtml(t) + '</button>'
    ).join('') + '</div>' +
      '<div class="db-test-hint">点击表名加入「表名」输入框，再点一次移除</div>';
  } else {
    html += '<div class="db-test-hint">库中没有可读取的表</div>';
  }
  box.innerHTML = html;
  syncDbTableChips();
}

function toggleDbTable(btn) {
  const input = document.getElementById('edbTables');
  if (!input) return;
  const table = btn.getAttribute('data-table') || '';
  if (!table) return;
  const parts = input.value.split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean);
  const idx = parts.indexOf(table);
  if (idx >= 0) parts.splice(idx, 1); else parts.push(table);
  input.value = parts.join(', ');
  syncDbTableChips();
}

// 输入框手动改动时，同步表名 chip 的选中态
function syncDbTableChips() {
  const input = document.getElementById('edbTables');
  if (!input) return;
  const selected = input.value.split(/[,，;；\n]/).map(s => s.trim()).filter(Boolean);
  document.querySelectorAll('#edbTestResult .db-table-chip').forEach(chip => {
    chip.classList.toggle('selected', selected.indexOf(chip.getAttribute('data-table')) >= 0);
  });
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
