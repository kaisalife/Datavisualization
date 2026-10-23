// ===== 设置面板：模型 / 提示词 / 数据库 / 服务连接 =====
// 模型和数据库配置都支持完整的增删改查；新增/编辑/删除后立即持久化，
// 提示词与服务连接仍由底部「保存设置」统一提交。
let editingDbId = null;
let editingModelId = null;
let settingsPane = 'models';

function _settingsNewId(prefix) {
  return prefix + '_' + Date.now() + '_' + Math.random().toString(16).slice(2, 8);
}

function _isDraftConfig(item) {
  return !!(item && item._draft);
}

function _settingsTabButton(pane, icon, label, count) {
  return '<button type="button" class="settings-tab" role="tab" aria-selected="false" data-pane="' + pane + '" onclick="switchSettingsPane(\'' + pane + '\',this)">' +
    '<span class="settings-tab-icon" aria-hidden="true">' + icon + '</span>' +
    '<span>' + label + '</span>' +
    (typeof count === 'number' ? '<span class="settings-tab-count">' + count + '</span>' : '') +
    '</button>';
}

function _settingsSectionActions(manageId, manageFn, addFn, addLabel) {
  return '<div class="settings-section-actions">' +
    '<button type="button" class="settings-manage-btn" id="' + manageId + '" onclick="' + manageFn + '()" aria-pressed="false" data-tip="批量管理">批量</button>' +
    '<button type="button" class="settings-add-btn" onclick="' + addFn + '()"><span>+</span>' + addLabel + '</button>' +
    '</div>';
}

function renderSettings(cfg) {
  state.modelConfigs = (cfg.modelConfigs || state.modelConfigs || []).filter(m => m && !_isDraftConfig(m));
  state.dbConfigs = (cfg.dbConfigs || state.dbConfigs || []).filter(db => db && !_isDraftConfig(db));
  state.modelSelectMode = false;
  state.selectedModelIds = [];
  state.dbSelectMode = false;
  state.selectedDbIds = [];
  editingModelId = null;
  editingDbId = null;
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
        '<div><div class="settings-section-title">模型配置</div><div class="settings-section-desc">图表生成、规划、抽表与 AI 润色共用这里的模型凭证；增删改会立即写入本机</div></div>' +
        _settingsSectionActions('modelManageBtn', 'toggleModelSelectMode', 'addModelConfigForm', '添加模型') +
      '</div>' +
      '<div class="settings-batch-bar batch-bar" id="modelBatchBar" style="display:none"></div>' +
      '<div class="db-list" id="modelList"></div>' +
      '<div class="settings-tip"><span class="settings-tip-icon">ⓘ</span>同时只会启用一个模型；用右侧开关切换，保存后新任务立即生效。批量模式下可以一次删除多个配置。</div>' +
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
        '<div class="settings-prompt-actions"><button type="button" class="settings-inline-btn" onclick="clearPromptFields()">清空两段提示词</button></div>' +
      '</div>' +
    '</div>' +
    '<div class="settings-pane" role="tabpanel" id="settingsPane-database">' +
      '<div class="settings-section-head">' +
        '<div><div class="settings-section-title">数据库连接</div><div class="settings-section-desc">供数据预览与图表任务读取；查询只允许只读 SELECT，增删改会立即写入本机</div></div>' +
        _settingsSectionActions('dbManageBtn', 'toggleDbSelectMode', 'addDbConfigForm', '添加连接') +
      '</div>' +
      '<div class="settings-batch-bar batch-bar" id="dbBatchBar" style="display:none"></div>' +
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
        '<div><div class="settings-status-title">连接与保存</div><div class="settings-status-sub">提示词与服务连接点底部「保存设置」生效；模型和数据库配置在增删改时已即时保存。</div></div>' +
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
  const models = (state.modelConfigs || []).filter(m => m && !_isDraftConfig(m));
  const active = models.filter(m => m && m.enabled)[0];
  const dbs = (state.dbConfigs || []).filter(db => db && !_isDraftConfig(db));
  const modelTabCount = document.querySelector('#settingsBody .settings-tab[data-pane="models"] .settings-tab-count');
  const dbTabCount = document.querySelector('#settingsBody .settings-tab[data-pane="database"] .settings-tab-count');
  if (modelTabCount) modelTabCount.textContent = String(models.length);
  if (dbTabCount) dbTabCount.textContent = String(dbs.length);
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

function clearPromptFields() {
  const mcp = document.getElementById('setMcp');
  const skill = document.getElementById('setSkill');
  if (mcp) mcp.value = '';
  if (skill) skill.value = '';
  window.app.showToast('已清空提示词，记得点底部「保存设置」', 'info');
}

// ===== 模型配置 CRUD + 批量管理 =====

function _modelVisibleIds() {
  return (state.modelConfigs || [])
    .filter(m => m && !_isDraftConfig(m) && m.id)
    .map(m => m.id);
}

function _pruneModelSelection() {
  const ids = _modelVisibleIds();
  state.selectedModelIds = (state.selectedModelIds || []).filter(id => ids.indexOf(id) >= 0);
}

function _modelUrlLabel(url) {
  return String(url || '').replace(/^https?:\/\//, '').replace(/\/+$/, '') || '未填写 API URL';
}

function renderModelList() {
  const list = document.getElementById('modelList');
  if (!list) return;
  _pruneModelSelection();
  const configs = state.modelConfigs || [];
  if (configs.length === 0) {
    list.innerHTML = '<div class="settings-empty"><div class="settings-empty-icon">🤖</div><div class="settings-empty-title">还没有模型配置</div><div class="settings-empty-sub">添加一个模型后，图表生成与 AI 润色才能使用</div></div>';
    renderModelBatchBar();
    updateSettingsHero();
    return;
  }
  const selectedIds = state.selectedModelIds || [];
  list.innerHTML = configs.map((m, idx) => {
    if (editingModelId === idx) {
      return '<div class="db-form settings-edit-card">' +
        '<div class="settings-edit-head"><span class="settings-edit-title">' + (m._draft ? '新增模型配置' : '编辑模型配置') + '</span><span class="settings-edit-hint">保存后立即写入本机</span></div>' +
        '<div class="form-group"><label class="form-label">配置名称</label><input class="form-input" id="emName" value="' + escAttr(m.name || '') + '" placeholder="例如：视觉模型 / 主力模型"></div>' +
        '<div class="form-group"><label class="form-label">模型名称</label><input class="form-input" id="emType" value="' + escAttr(m.modelType || '') + '" placeholder="例如 deepseek-v4.1-flash"></div>' +
        '<div class="form-group"><label class="form-label">API URL</label><input class="form-input" id="emUrl" value="' + escAttr(m.modelUrl || '') + '" placeholder="https://open.bigmodel.cn/api/paas/v4/"></div>' +
        '<div class="form-group"><label class="form-label">API Key</label><input class="form-input" type="password" id="emKey" value="' + escAttr(m.modelApiKey || '') + '" placeholder="sk-..."></div>' +
        '<div class="db-form-actions"><button class="btn btn-primary" onclick="saveModelEdit(' + idx + ')">保存</button><button class="btn btn-ghost" onclick="cancelModelEdit()">取消</button></div>' +
      '</div>';
    }
    const enabled = !!m.enabled;
    const selected = state.modelSelectMode && selectedIds.indexOf(m.id) >= 0;
    const checkbox = state.modelSelectMode
      ? '<input type="checkbox" class="row-checkbox settings-row-check" tabindex="-1" aria-label="选择模型 ' + escAttr(m.name || '未命名') + '"' + (selected ? ' checked' : '') + '>'
      : '';
    const actions = (state.modelSelectMode || editingModelId !== null) ? '' :
      '<div class="model-card-actions">' +
        '<label class="toggle-switch" data-tip="' + (enabled ? '当前已启用' : '启用这个模型') + '">' +
          '<input type="radio" name="modelEnabled" ' + (enabled ? 'checked' : '') + ' onchange="enableModel(' + idx + ')" aria-label="启用模型 ' + escAttr(m.name || '') + '">' +
          '<span class="toggle-track" aria-hidden="true"></span>' +
        '</label>' +
        '<button class="db-edit-btn" onclick="editModel(' + idx + ')">编辑</button>' +
        '<button class="db-del-btn" onclick="deleteModelConfig(' + idx + ')">删除</button>' +
      '</div>';
    const selectableAttrs = state.modelSelectMode
      ? ' tabindex="0" role="button" aria-label="选择模型 ' + escAttr(m.name || '未命名') + '"'
      : '';
    return '<div class="db-config-card model-card' + (enabled ? ' db-config-active' : '') + (selected ? ' selected' : '') + '" data-model-id="' + escAttr(m.id || '') + '"' + selectableAttrs + '>' +
      checkbox +
      '<div class="model-card-icon" aria-hidden="true">' + (enabled ? '✨' : '🤖') + '</div>' +
      '<div class="model-card-main">' +
        '<div class="model-card-top"><span class="db-config-name">' + escHtml(m.name || '未命名模型') + '</span>' +
          (enabled ? '<span class="model-status on">已启用</span>' : '<span class="model-status">未启用</span>') + '</div>' +
        '<div class="model-meta"><span class="model-type-chip">' + escHtml(m.modelType || '未填写模型') + '</span><span class="model-url" title="' + escAttr(m.modelUrl || '') + '">' + escHtml(_modelUrlLabel(m.modelUrl)) + '</span></div>' +
        '<div class="model-key">API Key ' + (m.modelApiKey ? '已配置' : '未配置') + '</div>' +
      '</div>' +
      actions +
    '</div>';
  }).join('');
  renderModelBatchBar();
  updateSettingsHero();
}

function renderModelBatchBar() {
  const bar = document.getElementById('modelBatchBar');
  const manage = document.getElementById('modelManageBtn');
  const total = _modelVisibleIds().length;
  if (manage) {
    manage.disabled = total === 0;
    manage.classList.toggle('active', !!state.modelSelectMode);
    manage.setAttribute('aria-pressed', state.modelSelectMode ? 'true' : 'false');
    manage.setAttribute('data-tip', state.modelSelectMode ? '退出批量管理' : '批量管理模型配置');
    manage.setAttribute('aria-label', state.modelSelectMode ? '退出批量管理' : '批量管理模型配置');
  }
  if (!bar) return;
  if (!state.modelSelectMode) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }
  const n = (state.selectedModelIds || []).length;
  bar.style.display = 'flex';
  bar.innerHTML = '<span class="batch-count">已选 <strong>' + n + '</strong> / ' + total + ' 个模型</span>' +
    '<button class="btn-sm" onclick="selectAllModels()" ' + (total === 0 ? 'disabled' : '') + '>全选</button>' +
    '<button class="btn-sm" onclick="selectNoneModels()" ' + (n === 0 ? 'disabled' : '') + '>全不选</button>' +
    '<button class="btn-sm danger" onclick="batchDeleteModels()" ' + (n === 0 ? 'disabled' : '') + '>删除</button>' +
    '<button class="btn-sm ghost" onclick="toggleModelSelectMode()">取消</button>';
}

function toggleModelSelectMode() {
  if (editingModelId !== null) cancelModelEdit();
  state.modelSelectMode = !state.modelSelectMode;
  state.selectedModelIds = [];
  renderModelList();
}

function _toggleModelSelection(id) {
  if (!id) return;
  state.selectedModelIds = state.selectedModelIds || [];
  const idx = state.selectedModelIds.indexOf(id);
  const on = idx < 0;
  if (on) state.selectedModelIds.push(id);
  else state.selectedModelIds.splice(idx, 1);
  const rows = document.querySelectorAll('#modelList .model-card[data-model-id]');
  for (const row of rows) {
    if (row.getAttribute('data-model-id') !== id) continue;
    row.classList.toggle('selected', on);
    const cb = row.querySelector('.settings-row-check');
    if (cb) cb.checked = on;
    break;
  }
  renderModelBatchBar();
}

function selectAllModels() {
  state.selectedModelIds = _modelVisibleIds();
  renderModelList();
}

function selectNoneModels() {
  state.selectedModelIds = [];
  renderModelList();
}

function _persistModelConfigs() {
  sendToRust('syncModelConfigs', {
    modelConfigs: (state.modelConfigs || []).filter(m => m && !_isDraftConfig(m)),
  });
}

function addModelConfigForm() {
  if (editingModelId !== null) cancelModelEdit();
  state.modelSelectMode = false;
  state.selectedModelIds = [];
  settingsPane = 'models';
  applySettingsPane();
  const hasEnabled = (state.modelConfigs || []).some(m => m && !_isDraftConfig(m) && m.enabled);
  state.modelConfigs.push({
    id: _settingsNewId('model'),
    name: '',
    modelType: '',
    modelUrl: '',
    modelApiKey: '',
    enabled: !hasEnabled,
    _draft: true,
  });
  editingModelId = state.modelConfigs.length - 1;
  renderModelList();
  setTimeout(() => {
    const el = document.getElementById('emName');
    if (el) { el.focus(); el.select(); }
  }, 30);
}

function editModel(idx) {
  const target = state.modelConfigs[idx];
  if (!target) return;
  if (editingModelId !== null && editingModelId !== idx) cancelModelEdit();
  editingModelId = state.modelConfigs.indexOf(target);
  renderModelList();
}

function cancelModelEdit() {
  const current = editingModelId !== null ? state.modelConfigs[editingModelId] : null;
  if (current && current._draft) state.modelConfigs.splice(editingModelId, 1);
  editingModelId = null;
  renderModelList();
}

function saveModelEdit(idx) {
  const m = state.modelConfigs[idx];
  if (!m) return;
  const name = ((document.getElementById('emName') || {}).value || '').trim();
  if (!name) {
    window.app.showToast('请填写配置名称', 'error');
    return;
  }
  m.name = name;
  m.modelType = ((document.getElementById('emType') || {}).value || '').trim();
  m.modelUrl = ((document.getElementById('emUrl') || {}).value || '').trim();
  m.modelApiKey = (document.getElementById('emKey') || {}).value || '';
  delete m._draft;
  if (!(state.modelConfigs || []).some(item => item && !_isDraftConfig(item) && item.enabled)) {
    m.enabled = true;
  }
  editingModelId = null;
  renderModelList();
  _persistModelConfigs();
  window.app.showToast('模型配置已保存', 'success');
}

function deleteModelConfig(idx) {
  const m = state.modelConfigs[idx];
  if (!m) return;
  if (!window.confirm('确定删除模型配置「' + (m.name || '未命名') + '」吗？')) return;
  state.modelConfigs.splice(idx, 1);
  if (editingModelId === idx) editingModelId = null;
  else if (editingModelId !== null && editingModelId > idx) editingModelId -= 1;
  if (state.modelConfigs.length && !state.modelConfigs.some(item => item && item.enabled)) {
    state.modelConfigs[0].enabled = true;
  }
  renderModelList();
  _persistModelConfigs();
  window.app.showToast('模型配置已删除', 'info');
}

function batchDeleteModels() {
  const ids = (state.selectedModelIds || []).slice();
  if (!ids.length) {
    window.app.showToast('未选择模型配置', 'info');
    return;
  }
  if (!window.confirm('确定删除选中的 ' + ids.length + ' 个模型配置吗？该操作不可撤销。')) return;
  state.modelConfigs = (state.modelConfigs || []).filter(m => !m || ids.indexOf(m.id) < 0);
  if (state.modelConfigs.length && !state.modelConfigs.some(item => item && item.enabled)) {
    state.modelConfigs[0].enabled = true;
  }
  state.modelSelectMode = false;
  state.selectedModelIds = [];
  editingModelId = null;
  renderModelList();
  _persistModelConfigs();
  window.app.showToast('已删除 ' + ids.length + ' 个模型配置', 'success');
}

function enableModel(idx) {
  (state.modelConfigs || []).forEach((m, i) => { m.enabled = i === idx; });
  renderModelList();
  sendToRust('enableModel', { index: idx, modelConfigs: state.modelConfigs });
}

// ===== 数据库配置 CRUD + 批量管理 =====

function _dbVisibleIds() {
  return (state.dbConfigs || [])
    .filter(db => db && !_isDraftConfig(db) && db.id)
    .map(db => db.id);
}

function _pruneDbSelection() {
  const ids = _dbVisibleIds();
  state.selectedDbIds = (state.selectedDbIds || []).filter(id => ids.indexOf(id) >= 0);
}

function renderDbList() {
  const list = document.getElementById('dbList');
  if (!list) return;
  _pruneDbSelection();
  if (!state.dbConfigs || state.dbConfigs.length === 0) {
    list.innerHTML = '<div class="settings-empty"><div class="settings-empty-icon">🗄️</div><div class="settings-empty-title">还没有数据库连接</div><div class="settings-empty-sub">添加后可在输入区选择数据库，直接读取表或执行只读 SQL</div></div>';
    renderDbBatchBar();
    updateSettingsHero();
    return;
  }
  const selectedIds = state.selectedDbIds || [];
  list.innerHTML = state.dbConfigs.map((db, idx) => {
    const typeCls = 'db-type-' + (db.dbType || 'mysql').toLowerCase().replace(/\s/g, '');
    const scope = (db.query || '').trim()
      ? '自定义 SQL'
      : ((db.tables || '').trim() ? '表: ' + db.tables.trim() : '全部表');
    if (editingDbId === idx) {
      return '<div class="db-form settings-edit-card">' +
        '<div class="settings-edit-head"><span class="settings-edit-title">' + (db._draft ? '新增数据库连接' : '编辑数据库连接') + '</span><span class="settings-edit-hint">保存后立即写入本机</span></div>' +
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
    const selected = state.dbSelectMode && selectedIds.indexOf(db.id) >= 0;
    const checkbox = state.dbSelectMode
      ? '<input type="checkbox" class="row-checkbox settings-row-check" tabindex="-1" aria-label="选择数据库 ' + escAttr(db.name || '未命名') + '"' + (selected ? ' checked' : '') + '>'
      : '';
    const actions = (state.dbSelectMode || editingDbId !== null) ? '' :
      '<div class="db-card-actions"><button class="db-edit-btn" onclick="editDb(' + idx + ')">编辑</button><button class="db-del-btn" onclick="deleteDbConfig(' + idx + ')">删除</button></div>';
    const selectableAttrs = state.dbSelectMode
      ? ' tabindex="0" role="button" aria-label="选择数据库 ' + escAttr(db.name || '未命名') + '"'
      : '';
    return '<div class="db-config-card db-card' + (selected ? ' selected' : '') + '" data-db-id="' + escAttr(db.id || '') + '"' + selectableAttrs + '>' +
      checkbox +
      '<div class="db-card-icon" aria-hidden="true">' + (db.dbType === 'SQLite' ? '📄' : '🗄️') + '</div>' +
      '<div class="db-card-main">' +
        '<div class="db-config-header"><div class="db-config-name">' + escHtml(db.name) + '</div><div class="db-config-type ' + typeCls + '">' + escHtml(db.dbType) + '</div></div>' +
        '<div class="db-config-detail">' + escHtml(db.host || '-') + ':' + escHtml(db.port || '-') + ' / ' + escHtml(db.database || '-') + '</div>' +
        '<div class="db-scope-chip">' + escHtml(scope) + '</div>' +
      '</div>' +
      actions +
    '</div>';
  }).join('');
  renderDbBatchBar();
  updateSettingsHero();
}

function renderDbBatchBar() {
  const bar = document.getElementById('dbBatchBar');
  const manage = document.getElementById('dbManageBtn');
  const total = _dbVisibleIds().length;
  if (manage) {
    manage.disabled = total === 0;
    manage.classList.toggle('active', !!state.dbSelectMode);
    manage.setAttribute('aria-pressed', state.dbSelectMode ? 'true' : 'false');
    manage.setAttribute('data-tip', state.dbSelectMode ? '退出批量管理' : '批量管理数据库连接');
    manage.setAttribute('aria-label', state.dbSelectMode ? '退出批量管理' : '批量管理数据库连接');
  }
  if (!bar) return;
  if (!state.dbSelectMode) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }
  const n = (state.selectedDbIds || []).length;
  bar.style.display = 'flex';
  bar.innerHTML = '<span class="batch-count">已选 <strong>' + n + '</strong> / ' + total + ' 个连接</span>' +
    '<button class="btn-sm" onclick="selectAllDbs()" ' + (total === 0 ? 'disabled' : '') + '>全选</button>' +
    '<button class="btn-sm" onclick="selectNoneDbs()" ' + (n === 0 ? 'disabled' : '') + '>全不选</button>' +
    '<button class="btn-sm danger" onclick="batchDeleteDbs()" ' + (n === 0 ? 'disabled' : '') + '>删除</button>' +
    '<button class="btn-sm ghost" onclick="toggleDbSelectMode()">取消</button>';
}

function toggleDbSelectMode() {
  if (editingDbId !== null) cancelDbEdit();
  state.dbSelectMode = !state.dbSelectMode;
  state.selectedDbIds = [];
  renderDbList();
}

function _toggleDbSelection(id) {
  if (!id) return;
  state.selectedDbIds = state.selectedDbIds || [];
  const idx = state.selectedDbIds.indexOf(id);
  const on = idx < 0;
  if (on) state.selectedDbIds.push(id);
  else state.selectedDbIds.splice(idx, 1);
  const rows = document.querySelectorAll('#dbList .db-card[data-db-id]');
  for (const row of rows) {
    if (row.getAttribute('data-db-id') !== id) continue;
    row.classList.toggle('selected', on);
    const cb = row.querySelector('.settings-row-check');
    if (cb) cb.checked = on;
    break;
  }
  renderDbBatchBar();
}

function selectAllDbs() {
  state.selectedDbIds = _dbVisibleIds();
  renderDbList();
}

function selectNoneDbs() {
  state.selectedDbIds = [];
  renderDbList();
}

function _persistDbConfigs() {
  sendToRust('syncDbConfigs', {
    dbConfigs: (state.dbConfigs || []).filter(db => db && !_isDraftConfig(db)),
  });
}

function addDbConfigForm() {
  if (editingDbId !== null) cancelDbEdit();
  state.dbSelectMode = false;
  state.selectedDbIds = [];
  settingsPane = 'database';
  applySettingsPane();
  state.dbConfigs.push({
    id: _settingsNewId('db'),
    name: '',
    dbType: 'MySQL',
    host: 'localhost',
    port: '3306',
    user: 'root',
    password: '',
    database: '',
    tables: '',
    query: '',
    _draft: true,
  });
  editingDbId = state.dbConfigs.length - 1;
  renderDbList();
  setTimeout(() => {
    const el = document.getElementById('edbName');
    if (el) { el.focus(); el.select(); }
  }, 30);
}

function editDb(idx) {
  const target = state.dbConfigs[idx];
  if (!target) return;
  if (editingDbId !== null && editingDbId !== idx) cancelDbEdit();
  editingDbId = state.dbConfigs.indexOf(target);
  renderDbList();
}

function cancelDbEdit() {
  const current = editingDbId !== null ? state.dbConfigs[editingDbId] : null;
  if (current && current._draft) state.dbConfigs.splice(editingDbId, 1);
  editingDbId = null;
  renderDbList();
}

function saveDbEdit(idx) {
  const db = state.dbConfigs[idx];
  if (!db) return;
  const name = ((document.getElementById('edbName') || {}).value || '').trim();
  if (!name) {
    window.app.showToast('请填写连接名称', 'error');
    return;
  }
  db.name = name;
  db.dbType = (document.getElementById('edbType') || {}).value || 'MySQL';
  db.host = ((document.getElementById('edbHost') || {}).value || '').trim();
  db.port = ((document.getElementById('edbPort') || {}).value || '').trim();
  db.user = ((document.getElementById('edbUser') || {}).value || '').trim();
  db.password = (document.getElementById('edbPass') || {}).value || '';
  db.database = ((document.getElementById('edbDb') || {}).value || '').trim();
  db.tables = (document.getElementById('edbTables') || {}).value || '';
  db.query = (document.getElementById('edbQuery') || {}).value || '';
  delete db._draft;
  editingDbId = null;
  renderDbList();
  _persistDbConfigs();
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
  _persistDbConfigs();
  window.app.showToast('数据库配置已删除', 'info');
}

function batchDeleteDbs() {
  const ids = (state.selectedDbIds || []).slice();
  if (!ids.length) {
    window.app.showToast('未选择数据库连接', 'info');
    return;
  }
  if (!window.confirm('确定删除选中的 ' + ids.length + ' 个数据库连接吗？该操作不可撤销。')) return;
  state.dbConfigs = (state.dbConfigs || []).filter(db => !db || ids.indexOf(db.id) < 0);
  state.dbSelectMode = false;
  state.selectedDbIds = [];
  editingDbId = null;
  renderDbList();
  _persistDbConfigs();
  window.app.showToast('已删除 ' + ids.length + ' 个数据库连接', 'success');
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
    modelConfigs: (state.modelConfigs || []).filter(m => m && !_isDraftConfig(m)),
    mcp: (document.getElementById('setMcp') || {}).value || '',
    skill: (document.getElementById('setSkill') || {}).value || '',
    backend: (document.getElementById('setBackend') || {}).value || '',
    apiKey: (document.getElementById('setApiKey') || {}).value || '',
    dbConfigs: (state.dbConfigs || []).filter(db => db && !_isDraftConfig(db)),
  };
  sendToRust('saveSettings', data);
}

(function initSettingsRowEvents() {
  const body = document.getElementById('settingsBody');
  if (!body) return;
  body.addEventListener('click', function (ev) {
    if (state.modelSelectMode) {
      const modelRow = ev.target.closest ? ev.target.closest('.model-card[data-model-id]') : null;
      if (modelRow) {
        _toggleModelSelection(modelRow.getAttribute('data-model-id'));
        return;
      }
    }
    if (state.dbSelectMode) {
      const dbRow = ev.target.closest ? ev.target.closest('.db-card[data-db-id]') : null;
      if (dbRow) {
        _toggleDbSelection(dbRow.getAttribute('data-db-id'));
        return;
      }
    }
  });
  body.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const row = ev.target.closest ? ev.target.closest('.model-card[data-model-id], .db-card[data-db-id]') : null;
    if (!row || ev.target !== row) return;
    if (state.modelSelectMode && row.hasAttribute('data-model-id')) {
      ev.preventDefault();
      _toggleModelSelection(row.getAttribute('data-model-id'));
    } else if (state.dbSelectMode && row.hasAttribute('data-db-id')) {
      ev.preventDefault();
      _toggleDbSelection(row.getAttribute('data-db-id'));
    }
  });
})();
