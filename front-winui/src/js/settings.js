// ===== 设置面板：模型 / 提示词 / 数据库 / 服务连接 =====
let editingDbId = null;
let editingModelId = null;
let settingsPane = 'models';

function _settingsTabButton(pane, icon, label, count) {
  return '<button type="button" class="settings-tab" role="tab" aria-selected="false" data-pane="' + pane + '" onclick="switchSettingsPane(\'' + pane + '\',this)">' +
    '<span class="settings-tab-icon" aria-hidden="true">' + icon + '</span>' +
    '<span>' + label + '</span>' +
    (typeof count === 'number' ? '<span class="settings-tab-count">' + count + '</span>' : '') +
    '</button>';
}

function renderSettings(cfg) {
  state.modelConfigs = cfg.modelConfigs || state.modelConfigs || [];
  state.dbConfigs = cfg.dbConfigs || state.dbConfigs || [];
  const body = document.getElementById('settingsBody');
  if (!body) return;

  body.innerHTML =
    '<div class="settings-hero" id="settingsHero"></div>' +
    '<div class="settings-tabs" role="tablist" aria-label="设置分类">' +
      _settingsTabButton('models', '🤖', '模型', (state.modelConfigs || []).length) +
      _settingsTabButton('prompts', '💡', '提示词') +
      _settingsTabButton('database', '🗄️', '数据库', (state.dbConfigs || []).length) +
      _settingsTabButton('service', '🔌', '服务连接') +
    '</div>' +
    '<div class="settings-pane" role="tabpanel" id="settingsPane-models">' +
      '<div class="settings-section-head">' +
        '<div><div class="settings-section-title">模型配置</div><div class="settings-section-desc">图表生成、规划、抽表与 AI 润色共用这里的模型凭证</div></div>' +
        '<button type="button" class="settings-add-btn" onclick="addModelConfigForm()"><span>+</span>添加模型</button>' +
      '</div>' +
      '<div class="db-list" id="modelList"></div>' +
      '<div class="settings-tip"><span class="settings-tip-icon">ⓘ</span>同时只会启用一个模型；用右侧开关切换，保存后新任务立即生效。</div>' +
    '</div>' +
    '<div class="settings-pane" role="tabpanel" id="settingsPane-prompts">' +
      '<div class="settings-section-head"><div><div class="settings-section-title">提示词补充</div><div class="settings-section-desc">作为附加上下文注入到对应 Agent，留空表示不追加</div></div></div>' +
      '<div class="settings-form-card">' +
        '<label class="settings-field"><span class="settings-field-label">MCP 提示词</span>' +
          '<input class="form-input" id="setMcp" value="' + escAttr(cfg.mcp || '') + '" placeholder="例如：优先使用本地数据工具，减少不必要的联网调用">' +
          '<span class="settings-field-help">会拼接到 MCP 相关工具调用的系统提示中。</span></label>' +
        '<label class="settings-field"><span class="settings-field-label">技能提示词</span>' +
          '<input class="form-input" id="setSkill" value="' + escAttr(cfg.skill || '') + '" placeholder="例如：优先使用用户技能，业务口径以技能正文为准">' +
          '<span class="settings-field-help">用于强化技能加载与场景选择，不影响技能正文。</span></label>' +
      '</div>' +
    '</div>' +
    '<div class="settings-pane" role="tabpanel" id="settingsPane-database">' +
      '<div class="settings-section-head">' +
        '<div><div class="settings-section-title">数据库连接</div><div class="settings-section-desc">供数据预览与图表任务读取；查询只允许只读 SELECT</div></div>' +
        '<button type="button" class="settings-add-btn" onclick="addDbConfigForm()"><span>+</span>添加连接</button>' +
      '</div>' +
      '<div class="db-list" id="dbList"></div>' +
      '<div class="settings-tip"><span class="settings-tip-icon">ⓘ</span>「表名」与「自定义 SQL」同时填写时优先执行 SQL；连接测试在编辑表单内。</div>' +
    '</div>' +
    '<div class="settings-pane" role="tabpanel" id="settingsPane-service">' +
      '<div class="settings-section-head"><div><div class="settings-section-title">后端服务</div><div class="settings-section-desc">前端只通过本地桥接访问后端，这里的地址与密钥用于发起 HTTP 请求</div></div></div>' +
      '<div class="settings-form-card">' +
        '<label class="settings-field"><span class="settings-field-label">后端地址</span>' +
          '<input class="form-input" id="setBackend" value="' + escAttr(cfg.backend || '') + '" placeholder="http://localhost:5000">' +
          '<span class="settings-field-help">修改后需要重新连接；本地默认端口是 5000。</span></label>' +
        '<label class="settings-field"><span class="settings-field-label">服务 API Key</span>' +
          '<span class="settings-input-with-action"><input class="form-input" type="password" id="setApiKey" value="' + escAttr(cfg.apiKey || '') + '" placeholder="后端未启用鉴权时可留空"><button type="button" class="settings-inline-btn" onclick="toggleSecret(\'setApiKey\', this)" aria-label="显示或隐藏服务 API Key">显示</button></span>' +
          '<span class="settings-field-help">对应后端的 SERVICE_API_KEY；仅保存在本机 settings.json。</span></label>' +
      '</div>' +
      '<div class="settings-status-card">' +
        '<span class="settings-status-dot" id="settingsStatusDot"></span>' +
        '<div><div class="settings-status-title">连接与保存</div><div class="settings-status-sub">配置保存后会写入本机，不会同步到远端。服务状态可在右上角「就绪」提示查看。</div></div>' +
      '</div>' +
    '</div>';

  applySettingsPane();
  updateSettingsHero();
  renderModelList();
  renderDbList();
}

function updateSettingsHero() {
  const hero = document.getElementById('settingsHero');
  if (!hero) return;
  const models = state.modelConfigs || [];
  const active = models.filter(m => m && m.enabled)[0];
  const dbs = state.dbConfigs || [];
  hero.innerHTML =
    '<div class="settings-hero-card primary">' +
      '<div class="settings-hero-label">当前启用模型</div>' +
      '<div class="settings-hero-value">' + escHtml(active ? (active.name || active.modelType || '未命名模型') : '未启用') + '</div>' +
      '<div class="settings-hero-sub">' + (active ? escHtml(active.modelType || '模型名称未填写') : '请在「模型」页启用一个配置') + '</div>' +
    '</div>' +
    '<div class="settings-hero-card"><div class="settings-hero-label">模型配置</div><div class="settings-hero-value">' + models.length + '</div><div class="settings-hero-sub">已启用 ' + models.filter(m => m && m.enabled).length + ' 个</div></div>' +
    '<div class="settings-hero-card"><div class="settings-hero-label">数据库连接</div><div class="settings-hero-value">' + dbs.length + '</div><div class="settings-hero-sub">只读查询</div></div>';
}

function switchSettingsPane(pane, el) {
  settingsPane = pane;
  applySettingsPane();
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function applySettingsPane() {
  document.querySelectorAll('#settingsBody .settings-tab').forEach(tab => {
    const on = tab.getAttribute('data-pane') === settingsPane;
    tab.classList.toggle('active', on);
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('#settingsBody .settings-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === 'settingsPane-' + settingsPane);
  });
}

function toggleSecret(id, btn) {
  const input = document.getElementById(id);
  if (!input) return;
  const showing = input.type === 'text';
  input.type = showing ? 'password' : 'text';
  if (btn) {
    btn.textContent = showing ? '显示' : '隐藏';
    btn.setAttribute('aria-label', showing ? '显示服务 API Key' : '隐藏服务 API Key');
  }
}

function _modelUrlLabel(url) {
  return String(url || '').replace(/^https?:\/\//, '').replace(/\/+$/, '') || '未填写 API URL';
}

function renderModelList() {
  const list = document.getElementById('modelList');
  if (!list) return;
  const configs = state.modelConfigs || [];
  if (configs.length === 0) {
    list.innerHTML = '<div class="settings-empty"><div class="settings-empty-icon">🤖</div><div class="settings-empty-title">还没有模型配置</div><div class="settings-empty-sub">添加一个模型后，图表生成与 AI 润色才能使用</div></div>';
    updateSettingsHero();
    return;
  }
  list.innerHTML = configs.map((m, idx) => {
    if (editingModelId === idx) {
      return '<div class="db-form settings-edit-card">' +
        '<div class="settings-edit-head"><span class="settings-edit-title">编辑模型配置</span><span class="settings-edit-hint">修改后点保存生效</span></div>' +
        '<div class="form-group"><label class="form-label">配置名称</label><input class="form-input" id="emName" value="' + escAttr(m.name || '') + '" placeholder="例如：视觉模型 / 主力模型"></div>' +
        '<div class="form-group"><label class="form-label">模型名称</label><input class="form-input" id="emType" value="' + escAttr(m.modelType || '') + '" placeholder="例如 deepseek-v4.1-flash"></div>' +
        '<div class="form-group"><label class="form-label">API URL</label><input class="form-input" id="emUrl" value="' + escAttr(m.modelUrl || '') + '" placeholder="https://open.bigmodel.cn/api/paas/v4/"></div>' +
        '<div class="form-group"><label class="form-label">API Key</label><input class="form-input" type="password" id="emKey" value="' + escAttr(m.modelApiKey || '') + '" placeholder="sk-..."></div>' +
        '<div class="db-form-actions"><button class="btn btn-primary" onclick="saveModelEdit(' + idx + ')">保存</button><button class="btn btn-ghost" onclick="cancelModelEdit()">取消</button></div>' +
      '</div>';
    }
    const enabled = !!m.enabled;
    return '<div class="db-config-card model-card' + (enabled ? ' db-config-active' : '') + '">' +
      '<div class="model-card-icon" aria-hidden="true">' + (enabled ? '✨' : '🤖') + '</div>' +
      '<div class="model-card-main">' +
        '<div class="model-card-top"><span class="db-config-name">' + escHtml(m.name || '未命名模型') + '</span>' +
          (enabled ? '<span class="model-status on">已启用</span>' : '<span class="model-status">未启用</span>') + '</div>' +
        '<div class="model-meta"><span class="model-type-chip">' + escHtml(m.modelType || '未填写模型') + '</span><span class="model-url" title="' + escAttr(m.modelUrl || '') + '">' + escHtml(_modelUrlLabel(m.modelUrl)) + '</span></div>' +
        '<div class="model-key">API Key ' + (m.modelApiKey ? '已配置' : '未配置') + '</div>' +
      '</div>' +
      '<div class="model-card-actions">' +
        '<label class="toggle-switch" data-tip="' + (enabled ? '当前已启用' : '启用这个模型') + '">' +
          '<input type="radio" name="modelEnabled" ' + (enabled ? 'checked' : '') + ' onchange="enableModel(' + idx + ')" aria-label="启用模型 ' + escAttr(m.name || '') + '">' +
          '<span class="toggle-track" aria-hidden="true"></span>' +
        '</label>' +
        '<button class="db-edit-btn" onclick="editModel(' + idx + ')">编辑</button>' +
        '<button class="db-del-btn" onclick="deleteModelConfig(' + idx + ')">删除</button>' +
      '</div>' +
    '</div>';
  }).join('');
  updateSettingsHero();
}

function addModelConfigForm() {
  settingsPane = 'models';
  applySettingsPane();
  state.modelConfigs.push({ name: '新模型', modelType: '', modelUrl: '', modelApiKey: '', enabled: state.modelConfigs.length === 0 });
  editingModelId = state.modelConfigs.length - 1;
  renderModelList();
  setTimeout(() => {
    const el = document.getElementById('emName');
    if (el) { el.focus(); el.select(); }
  }, 30);
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
  const m = state.modelConfigs[idx];
  if (!m) return;
  if (!window.confirm('确定删除模型配置「' + (m.name || '未命名') + '」吗？')) return;
  state.modelConfigs.splice(idx, 1);
  if (editingModelId === idx) editingModelId = null;
  else if (editingModelId !== null && editingModelId > idx) editingModelId -= 1;
  if (state.modelConfigs.length && !state.modelConfigs.some(item => item.enabled)) {
    state.modelConfigs[0].enabled = true;
  }
  renderModelList();
  window.app.showToast('已删除', 'info');
  sendToRust('syncModelConfigs', { modelConfigs: state.modelConfigs });
}

function enableModel(idx) {
  (state.modelConfigs || []).forEach((m, i) => { m.enabled = i === idx; });
  renderModelList();
  sendToRust('enableModel', { index: idx, modelConfigs: state.modelConfigs });
}

function renderDbList() {
  const list = document.getElementById('dbList');
  if (!list) return;
  if (!state.dbConfigs || state.dbConfigs.length === 0) {
    list.innerHTML = '<div class="settings-empty"><div class="settings-empty-icon">🗄️</div><div class="settings-empty-title">还没有数据库连接</div><div class="settings-empty-sub">添加后可在输入区选择数据库，直接读取表或执行只读 SQL</div></div>';
    updateSettingsHero();
    return;
  }
  list.innerHTML = state.dbConfigs.map((db, idx) => {
    const typeCls = 'db-type-' + (db.dbType || 'mysql').toLowerCase().replace(/\s/g, '');
    const scope = (db.query || '').trim()
      ? '自定义 SQL'
      : ((db.tables || '').trim() ? '表: ' + db.tables.trim() : '全部表');
    if (editingDbId === idx) {
      return '<div class="db-form settings-edit-card">' +
        '<div class="settings-edit-head"><span class="settings-edit-title">编辑数据库连接</span><span class="settings-edit-hint">保存后用于预览与图表任务</span></div>' +
        '<div class="form-group"><label class="form-label">连接名称</label><input class="form-input" id="edbName" value="' + escAttr(db.name) + '"></div>' +
        '<div class="form-row"><div class="form-group"><label class="form-label">类型</label><select class="form-select" id="edbType">' + dbTypeOptions(db.dbType) + '</select></div>' +
        '<div class="form-group"><label class="form-label">主机</label><input class="form-input" id="edbHost" value="' + escAttr(db.host) + '"></div>' +
        '<div class="form-group" style="max-width:90px"><label class="form-label">端口</label><input class="form-input" id="edbPort" value="' + escAttr(db.port) + '"></div></div>' +
        '<div class="form-row"><div class="form-group"><label class="form-label">用户名</label><input class="form-input" id="edbUser" value="' + escAttr(db.user) + '"></div>' +
        '<div class="form-group"><label class="form-label">密码</label><input class="form-input" type="password" id="edbPass" value="' + escAttr(db.password || '') + '"></div></div>' +
        '<div class="form-group"><label class="form-label">数据库</label><input class="form-input" id="edbDb" value="' + escAttr(db.database || '') + '"></div>' +
        '<div class="form-group"><label class="form-label">表名（可选，逗号分隔）</label><input class="form-input" id="edbTables" value="' + escAttr(db.tables || '') + '" placeholder="留空读取全部表，如 sales,users" oninput="syncDbTableChips()"></div>' +
        '<div class="form-group"><label class="form-label">自定义 SQL（可选，优先于表名）</label><textarea class="form-input" id="edbQuery" rows="3" placeholder="SELECT * FROM sales WHERE ...">' + escHtml(db.query || '') + '</textarea></div>' +
        '<div class="db-form-actions"><button class="btn btn-primary" onclick="saveDbEdit(' + idx + ')">保存</button>' +
          '<button class="btn btn-ghost" onclick="testDbConnection()">测试连接</button>' +
          '<button class="btn btn-ghost" onclick="cancelDbEdit()">取消</button></div>' +
        '<div class="db-test-result" id="edbTestResult"></div>' +
      '</div>';
    }
    return '<div class="db-config-card db-card">' +
      '<div class="db-card-icon" aria-hidden="true">' + (db.dbType === 'SQLite' ? '📄' : '🗄️') + '</div>' +
      '<div class="db-card-main">' +
        '<div class="db-config-header"><div class="db-config-name">' + escHtml(db.name) + '</div><div class="db-config-type ' + typeCls + '">' + escHtml(db.dbType) + '</div></div>' +
        '<div class="db-config-detail">' + escHtml(db.host || '-') + ':' + escHtml(db.port || '-') + ' / ' + escHtml(db.database || '-') + '</div>' +
        '<div class="db-scope-chip">' + escHtml(scope) + '</div>' +
      '</div>' +
      '<div class="db-card-actions"><button class="db-edit-btn" onclick="editDb(' + idx + ')">编辑</button><button class="db-del-btn" onclick="deleteDbConfig(' + idx + ')">删除</button></div>' +
    '</div>';
  }).join('');
  updateSettingsHero();
}

function addDbConfigForm() {
  settingsPane = 'database';
  applySettingsPane();
  state.dbConfigs.push({ name: '新连接', dbType: 'MySQL', host: 'localhost', port: '3306', user: 'root', password: '', database: '', tables: '', query: '' });
  editingDbId = state.dbConfigs.length - 1;
  renderDbList();
  setTimeout(() => {
    const el = document.getElementById('edbName');
    if (el) { el.focus(); el.select(); }
  }, 30);
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
  const db = state.dbConfigs[idx];
  if (!db) return;
  if (!window.confirm('确定删除数据库连接「' + (db.name || '未命名') + '」吗？')) return;
  state.dbConfigs.splice(idx, 1);
  if (editingDbId === idx) editingDbId = null;
  else if (editingDbId !== null && editingDbId > idx) editingDbId -= 1;
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
      '<button type="button" class="db-table-chip" data-table="' + escAttr(t) + '" data-tip="点击加入表名" aria-label="加入表名 ' + escAttr(t) + '" onclick="toggleDbTable(this)">' + escHtml(t) + '</button>'
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
    mcp: (document.getElementById('setMcp') || {}).value || '',
    skill: (document.getElementById('setSkill') || {}).value || '',
    backend: (document.getElementById('setBackend') || {}).value || '',
    apiKey: (document.getElementById('setApiKey') || {}).value || '',
    dbConfigs: state.dbConfigs,
  };
  sendToRust('saveSettings', data);
}
