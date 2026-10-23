// ===== 技能管理：列表 / 搜索过滤 / 编辑 / AI 润色 / 保存 / 删除 =====
// 数据来自 Rust 桥（JS 不能直连后端）：
//   openSkillManager -> listSkills
//   点击某项       -> loadSkill
//   AI 润色        -> polishSkill（后端只返回草稿，不落盘）
//   保存/删除      -> saveSkill / deleteSkill（保存后后端立即 reload）

let skillSelectedName = '';   // 当前编辑的技能（新建时为空）
let skillOriginalName = '';   // 打开编辑器时的技能名，用于识别重命名
let skillCurrentSource = '';  // builtin / user
let skillCurrentInvalid = false;
let skillAll = [];            // 最近一次从后端拿到的完整技能列表
let skillFilterSource = 'all';
let skillSearchQuery = '';
let skillSelectMode = false;  // 批量管理（只允许选择用户技能）
let skillSelectedNames = [];
let skillVisibleNames = [];   // 当前筛选下可删除的用户技能

function openSkillManager() {
  const modal = document.getElementById('skillManagerModal');
  if (!modal) return;
  modal.classList.add('show');
  skillSelectMode = false;
  skillSelectedNames = [];
  startNewSkill();
  renderSkillBatchBar();
  sendToRust('listSkills', {});
  setTimeout(() => {
    const el = document.getElementById('skillPrompt');
    if (el) el.focus();
  }, 60);
}

function closeSkillManager() {
  const modal = document.getElementById('skillManagerModal');
  if (modal) modal.classList.remove('show');
}

function setSkillMeta(text) {
  const el = document.getElementById('skillMeta');
  if (el) el.textContent = text || '';
}

function _setSkillEditorHeading(name, sub) {
  const nameEl = document.getElementById('skillEditorName');
  const subEl = document.getElementById('skillEditorSub');
  if (nameEl) nameEl.textContent = name || '新建技能';
  if (subEl) subEl.textContent = sub || '描述一个场景，让 Agent 按你的口径出图';
}

function _renderSkillTags(tags) {
  const box = document.getElementById('skillMetaTags');
  if (!box) return;
  if (!tags || !tags.length) { box.innerHTML = ''; return; }
  box.innerHTML = tags.map(tag =>
    '<span class="skill-tag ' + escAttr(tag.cls || '') + '">' + escHtml(tag.text) + '</span>'
  ).join('');
}

function _skillFrontmatter(text) {
  const src = String(text || '').replace(/\r\n/g, '\n');
  const match = src.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const result = {};
  let openKey = '';
  function splitArray(raw) {
    return String(raw || '').split(',').map(item => item.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
  }
  match[1].split('\n').forEach(line => {
    if (!line.trim()) return;
    const kv = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (kv) {
      const key = kv[1];
      const value = kv[2].trim();
      if (value.charAt(0) === '[') {
        if (value.charAt(value.length - 1) === ']') {
          result[key] = splitArray(value.slice(1, -1));
          openKey = '';
        } else {
          result[key] = splitArray(value.slice(1));
          openKey = key;
        }
      } else {
        result[key] = value.replace(/^['"]|['"]$/g, '');
        openKey = '';
      }
      return;
    }
    if (!openKey) return;
    const trimmed = line.trim();
    const end = trimmed.indexOf(']');
    const body = end >= 0 ? trimmed.slice(0, end) : trimmed;
    result[openKey] = (result[openKey] || []).concat(splitArray(body));
    if (end >= 0) openKey = '';
  });
  return result;
}

function _refreshSkillTagsFromContent(content) {
  const meta = _skillFrontmatter(content);
  const tags = [];
  if (skillCurrentSource === 'user') tags.push({ text: '用户技能', cls: 'user' });
  else if (skillCurrentSource === 'builtin') tags.push({ text: '内置技能' });
  if (skillCurrentInvalid) tags.push({ text: '解析失败 · 修正后保存', cls: 'warn' });
  const charts = Array.isArray(meta.chart_types) ? meta.chart_types : [];
  charts.slice(0, 4).forEach(type => tags.push({ text: type, cls: 'chart' }));
  const tasks = Array.isArray(meta.analysis_tasks) ? meta.analysis_tasks : [];
  tasks.slice(0, 2).forEach(task => tags.push({ text: task, cls: 'muted' }));
  if (String(meta.require_keywords || '').toLowerCase() === 'true') tags.push({ text: '需场景词', cls: 'warn' });
  _renderSkillTags(tags);
  if (meta.title) _setSkillEditorHeading(meta.title, meta.description || '');
  return meta;
}

function _updateSkillStats() {
  const content = (document.getElementById('skillContent') || {}).value || '';
  const stat = document.getElementById('skillContentStats');
  if (!stat) return;
  const lines = content ? content.split(/\r?\n/).length : 0;
  stat.textContent = content ? (lines + ' 行 · ' + content.length + ' 字符') : 'frontmatter + 场景工作流';
}

function startNewSkill() {
  skillSelectedName = '';
  skillOriginalName = '';
  skillCurrentSource = '';
  skillCurrentInvalid = false;
  skillSelectMode = false;
  skillSelectedNames = [];
  const name = document.getElementById('skillName');
  const content = document.getElementById('skillContent');
  const prompt = document.getElementById('skillPrompt');
  const badge = document.getElementById('skillSourceBadge');
  const del = document.getElementById('skillDeleteBtn');
  if (name) { name.value = ''; name.disabled = false; }
  if (content) content.value = '';
  if (prompt) prompt.value = '';
  if (badge) badge.textContent = '';
  if (del) del.style.display = 'none';
  _setSkillEditorHeading('新建技能', '描述一个场景，让 Agent 按你的口径出图');
  _renderSkillTags([{ text: '草稿', cls: 'muted' }]);
  _updateSkillStats();
  setSkillMeta('技能名即目录名；保存后立即生效');
  highlightSkillItem('');
  _renderSkillListItems();
}

function highlightSkillItem(name) {
  document.querySelectorAll('.skill-list-item').forEach(el => {
    const active = el.getAttribute('data-name') === name;
    el.classList.toggle('active', active);
    if (active) el.setAttribute('aria-current', 'true');
    else el.removeAttribute('aria-current');
  });
}

function _skillMatches(skill) {
  if (skillFilterSource === 'user' && skill.source !== 'user') return false;
  if (skillFilterSource === 'builtin' && skill.source !== 'builtin') return false;
  if (!skillSearchQuery) return true;
  const charts = Array.isArray(skill.chart_types) ? skill.chart_types.join(' ') : '';
  const haystack = [skill.name, skill.title, skill.description, charts].join(' ').toLowerCase();
  return haystack.indexOf(skillSearchQuery) >= 0;
}

function _renderSkillListItems() {
  const box = document.getElementById('skillList');
  const count = document.getElementById('skillCount');
  if (!box) return;
  const filtered = skillAll.filter(_skillMatches);
  skillVisibleNames = filtered.filter(s => s && s.source === 'user').map(s => s.name);
  const visible = {};
  skillVisibleNames.forEach(name => { visible[name] = true; });
  skillSelectedNames = (skillSelectedNames || []).filter(name => visible[name]);
  if (count) {
    const users = skillAll.filter(s => s && s.source === 'user').length;
    count.textContent = (filtered.length === skillAll.length
      ? skillAll.length + ' 个技能'
      : filtered.length + ' / ' + skillAll.length + ' 个技能') +
      (users ? ' · ' + users + ' 个可管理' : '');
  }
  if (!filtered.length) {
    const empty = skillAll.length
      ? '没有匹配的技能，换个关键词或来源筛选试试。'
      : '还没有技能。用右侧 AI 润色创建一个。';
    box.innerHTML = '<div class="skill-empty"><div class="skill-empty-icon">🧩</div><div>' + empty + '</div></div>';
    renderSkillBatchBar();
    return;
  }
  box.innerHTML = filtered.map(s => {
    const isUser = s.source === 'user';
    const badge = isUser
      ? '<span class="skill-tag user">用户</span>'
      : '<span class="skill-tag">内置</span>';
    const override = s.overrides_builtin ? '<span class="skill-tag warn">覆盖内置</span>' : '';
    const invalid = s.invalid ? '<span class="skill-tag warn">解析失败</span>' : '';
    const checked = skillSelectMode && skillSelectedNames.indexOf(s.name) >= 0;
    const checkbox = skillSelectMode
      ? '<input type="checkbox" class="skill-select-check" tabindex="-1" aria-label="选择技能 ' + escAttr(s.name) + '"' +
        (checked ? ' checked' : '') + (isUser ? '' : ' disabled') + '>'
      : '';
    const rowCls = 'skill-list-item' +
      (checked ? ' selected' : '') +
      (skillSelectMode && !isUser ? ' select-disabled' : '') +
      (skillSelectMode ? ' selectable' : '');
    return '<div class="' + rowCls + '" data-name="' + escAttr(s.name) + '" data-source="' + escAttr(s.source || '') + '" role="button" tabindex="0">' +
      checkbox +
      '<div class="skill-item-top">' + badge + override + invalid + '</div>' +
      '<div class="skill-item-name">' + escHtml(s.title || s.name) + '</div>' +
      '<div class="skill-item-slug">' + escHtml(s.name) + '</div>' +
      '<div class="skill-item-desc">' + escHtml(s.description || '暂无描述') + '</div>' +
      '<span class="skill-item-arrow" aria-hidden="true">' + (skillSelectMode ? '' : '›') + '</span>' +
      '</div>';
  }).join('');
  if (skillSelectedName) highlightSkillItem(skillSelectedName);
  renderSkillBatchBar();
}

function renderSkillBatchBar() {
  const bar = document.getElementById('skillBatchBar');
  const manage = document.getElementById('skillManageBtn');
  const total = (skillVisibleNames || []).length;
  if (manage) {
    manage.disabled = !(skillAll || []).length;
    manage.classList.toggle('active', !!skillSelectMode);
    manage.setAttribute('aria-pressed', skillSelectMode ? 'true' : 'false');
    manage.setAttribute('data-tip', skillSelectMode ? '退出批量管理' : '批量管理用户技能');
    manage.setAttribute('aria-label', skillSelectMode ? '退出批量管理' : '批量管理用户技能');
  }
  if (!bar) return;
  if (!skillSelectMode) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }
  const n = (skillSelectedNames || []).length;
  bar.style.display = 'flex';
  bar.innerHTML = '<span class="batch-count">已选 <strong>' + n + '</strong> / ' + total + ' 个用户技能</span>' +
    '<button class="btn-sm" onclick="selectAllSkills()" ' + (total === 0 ? 'disabled' : '') + '>全选</button>' +
    '<button class="btn-sm" onclick="selectNoneSkills()" ' + (n === 0 ? 'disabled' : '') + '>全不选</button>' +
    '<button class="btn-sm danger" onclick="batchDeleteSkills()" ' + (n === 0 ? 'disabled' : '') + '>删除</button>' +
    '<button class="btn-sm ghost" onclick="toggleSkillSelectMode()">取消</button>';
}

function toggleSkillSelectMode() {
  if (skillSelectMode) {
    skillSelectMode = false;
    skillSelectedNames = [];
  } else {
    skillSelectMode = true;
    skillSelectedNames = [];
  }
  _renderSkillListItems();
}

function _toggleSkillSelection(name) {
  const skill = (skillAll || []).filter(s => s.name === name)[0];
  if (!skill) return;
  if (skill.source !== 'user') {
    window.app.showToast('内置技能不能删除；如需定制，请修改名称后另存为用户技能', 'info');
    return;
  }
  skillSelectedNames = skillSelectedNames || [];
  const idx = skillSelectedNames.indexOf(name);
  const on = idx < 0;
  if (on) skillSelectedNames.push(name);
  else skillSelectedNames.splice(idx, 1);
  const rows = document.querySelectorAll('#skillList .skill-list-item[data-name]');
  for (const row of rows) {
    if (row.getAttribute('data-name') !== name) continue;
    row.classList.toggle('selected', on);
    const cb = row.querySelector('.skill-select-check');
    if (cb) cb.checked = on;
    break;
  }
  renderSkillBatchBar();
}

function selectAllSkills() {
  skillSelectedNames = (skillVisibleNames || []).slice();
  _renderSkillListItems();
}

function selectNoneSkills() {
  skillSelectedNames = [];
  _renderSkillListItems();
}

function batchDeleteSkills() {
  const names = (skillSelectedNames || []).slice();
  if (!names.length) {
    window.app.showToast('未选择用户技能', 'info');
    return;
  }
  if (!window.confirm('确定删除选中的 ' + names.length + ' 个用户技能吗？' +
    '覆盖内置的同名技能删除后会自动恢复内置版本。')) return;
  skillSelectMode = false;
  skillSelectedNames = [];
  _renderSkillListItems();
  sendToRust('deleteSkills', { names: names });
}

// 技能列表（后端返回 {count, skills:[...], invalid_user_skills:[...]}）
window.app = window.app || {};
window.app.renderSkillList = function (jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { return; }
  const skills = (Array.isArray(data.skills) ? data.skills : []).filter(skill => skill && skill.name);
  const byName = {};
  skills.forEach(skill => {
    if (!skill || !skill.name) return;
    byName[skill.name] = skill;
  });
  // 目录里存在但解析失败的 SKILL.md 也要出现在管理列表里，否则用户只能去磁盘删文件。
  (Array.isArray(data.invalid_user_skills) ? data.invalid_user_skills : []).forEach(item => {
    const name = item && item.name ? String(item.name) : '';
    if (!name) return;
    if (byName[name]) {
      const existing = byName[name];
      existing.invalid = true;
      existing.source = 'user';
      existing.overrides_builtin = true;
      existing.title = existing.title || name;
      existing.description = 'SKILL.md 解析失败：修正 frontmatter 后保存，或删除该用户技能';
    } else {
      const entry = {
        name: name,
        title: '无法解析：' + name,
        description: 'SKILL.md 解析失败：点击后修正 frontmatter，或直接删除',
        source: 'user',
        invalid: true,
        chart_types: [],
        analysis_tasks: [],
      };
      skills.push(entry);
      byName[name] = entry;
    }
  });
  skillAll = skills;
  _renderSkillListItems();
};

function filterSkillList(value) {
  skillSearchQuery = String(value || '').trim().toLowerCase();
  _renderSkillListItems();
}

function setSkillFilter(source, el) {
  skillFilterSource = source || 'all';
  document.querySelectorAll('#skillFilterRow .skill-filter').forEach(btn => {
    const on = btn.getAttribute('data-source') === skillFilterSource;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  _renderSkillListItems();
}

function selectSkill(name) {
  if (skillSelectMode) {
    _toggleSkillSelection(name);
    return;
  }
  skillSelectedName = name;
  highlightSkillItem(name);
  sendToRust('loadSkill', { name: name });
}

// 单个技能全文（{name, source, content, overrides_builtin?}）
window.app.renderSkillDetail = function (jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { return; }
  skillSelectedName = data.name || '';
  skillOriginalName = data.name || '';
  skillCurrentSource = data.source || '';
  const listed = (skillAll || []).filter(s => s.name === data.name)[0];
  skillCurrentInvalid = !!(listed && listed.invalid);
  const name = document.getElementById('skillName');
  const content = document.getElementById('skillContent');
  const badge = document.getElementById('skillSourceBadge');
  const del = document.getElementById('skillDeleteBtn');
  if (name) name.value = data.name || '';
  if (content) content.value = data.content || '';
  if (badge) {
    badge.textContent = data.source === 'user'
      ? (skillCurrentInvalid
          ? '用户技能 · 解析失败，可修正后保存'
          : (data.overrides_builtin ? '用户技能 · 覆盖内置' : '用户技能 · 可编辑'))
      : '内置技能 · 只读，保存会创建同名用户技能';
  }
  if (del) del.style.display = data.source === 'user' ? '' : 'none';
  const meta = _refreshSkillTagsFromContent(data.content || '');
  if (!meta.title) _setSkillEditorHeading(data.name || '技能', meta.description || '');
  _updateSkillStats();
  if (data.source === 'user') {
    setSkillMeta(skillCurrentInvalid
      ? '修正 frontmatter 后保存即可恢复；修改名称保存会重命名'
      : '可直接修改正文；修改名称后保存会重命名该用户技能');
  } else {
    setSkillMeta('内置技能只读；保存同名会创建用户覆盖，改名称会另存为新技能');
  }
  highlightSkillItem(skillSelectedName);
};

// AI 润色：只生成草稿，不保存
function aiPolishSkill() {
  const prompt = (document.getElementById('skillPrompt') || {}).value || '';
  const name = (document.getElementById('skillName') || {}).value || '';
  const btn = document.getElementById('skillPolishBtn');
  if (!prompt.trim()) {
    window.app.showToast('先写一句需求描述，再点 AI 润色', 'error');
    return;
  }
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="skill-polish-spark">⏳</span>润色中...'; }
  setSkillMeta('AI 正在写技能，可能需要几十秒...');
  sendToRust('polishSkill', { prompt: prompt, name: name.trim() });
}

function _resetPolishButton() {
  const btn = document.getElementById('skillPolishBtn');
  if (!btn) return;
  btn.disabled = false;
  btn.innerHTML = '<span class="skill-polish-spark">✨</span>AI 润色';
}

window.app.onSkillPolishFailed = function (message) {
  _resetPolishButton();
  setSkillMeta(message || 'AI 润色失败，请稍后重试');
};

window.app.onSkillPolished = function (jsonStr) {
  _resetPolishButton();
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { return; }
  const content = document.getElementById('skillContent');
  const name = document.getElementById('skillName');
  if (content) content.value = data.content || '';
  if (name && !name.value.trim() && data.skill && data.skill.name) {
    name.value = data.skill.name;
  }
  const skill = data.skill || {};
  // 内置技能上做润色只是草稿：来源仍是内置，保存同名会创建覆盖，改名称则另存新技能。
  if (skillCurrentSource !== 'builtin') skillCurrentSource = 'user';
  skillCurrentInvalid = false;
  _refreshSkillTagsFromContent(data.content || '');
  if (skill.title) _setSkillEditorHeading(skill.title, skill.description || '');
  _updateSkillStats();
  setSkillMeta('草稿已生成：' + (skill.title || skill.name || '') +
    (skill.chart_types && skill.chart_types.length ? ' · ' + skill.chart_types.join('/') : '') +
    ' · 确认无误后点「保存技能」');
  window.app.showToast('AI 草稿已生成，请确认后保存', 'success');
};

function useSkillPromptPreset(btn) {
  const prompt = document.getElementById('skillPrompt');
  if (!prompt || !btn) return;
  prompt.value = btn.getAttribute('data-prompt') || '';
  prompt.focus();
  prompt.setSelectionRange(prompt.value.length, prompt.value.length);
}

function saveCurrentSkill() {
  const nameEl = document.getElementById('skillName');
  const name = ((nameEl || {}).value || '').trim();
  const content = (document.getElementById('skillContent') || {}).value || '';
  if (!name || !content.trim()) {
    window.app.showToast('技能名和 SKILL.md 内容都不能为空', 'error');
    return;
  }
  if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
    window.app.showToast('技能名只能用小写字母、数字和连字符，且不能以连字符开头', 'error');
    return;
  }
  const existing = (skillAll || []).filter(s => s && s.name === name)[0];
  if (existing && name !== skillOriginalName) {
    if (existing.source === 'user') {
      window.app.showToast('已存在同名用户技能「' + name + '」，请换一个名称或先删除它', 'error');
      return;
    }
    if (existing.source === 'builtin' &&
        !window.confirm('「' + name + '」是内置技能，保存会创建同名用户技能覆盖它。继续吗？')) {
      return;
    }
  }
  // 用户技能改名 = 保存新目录 + 删除旧目录；内置技能改名只是另存为新用户技能。
  const previousName = (skillCurrentSource === 'user' && skillOriginalName && skillOriginalName !== name)
    ? skillOriginalName
    : '';
  setSkillMeta(previousName ? '正在重命名并保存...' : '正在保存...');
  sendToRust('saveSkill', { name: name, content: content, previousName: previousName });
}

window.app.onSkillSaved = function (jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { data = {}; }
  const skill = data.skill || {};
  const renamedFrom = data.renamed_from || '';
  skillSelectedName = skill.name || skillSelectedName;
  skillOriginalName = skillSelectedName;
  skillCurrentSource = 'user';
  skillCurrentInvalid = false;
  const nameEl = document.getElementById('skillName');
  if (nameEl && skill.name) nameEl.value = skill.name;
  const badge = document.getElementById('skillSourceBadge');
  if (badge) badge.textContent = '用户技能 · 可编辑';
  const del = document.getElementById('skillDeleteBtn');
  if (del) del.style.display = '';
  _refreshSkillTagsFromContent((document.getElementById('skillContent') || {}).value || '');
  _updateSkillStats();
  if (data.rename_error) {
    setSkillMeta('新技能已保存，但旧技能删除失败：' + data.rename_error);
    window.app.showToast('新技能已保存，旧技能未删除', 'error');
  } else if (renamedFrom) {
    setSkillMeta('已从「' + renamedFrom + '」重命名，下一次规划/生成就会用新名称');
    window.app.showToast('技能已重命名', 'success');
  } else {
    setSkillMeta('已保存，下一次规划/生成就会用上');
    window.app.showToast('技能已保存', 'success');
  }
  sendToRust('listSkills', {});
};

function deleteCurrentSkill() {
  if (!skillSelectedName) return;
  if (!window.confirm('确定删除技能「' + skillSelectedName + '」吗？' +
    '如果是覆盖内置的同名技能，删除后会自动恢复内置版本。')) return;
  sendToRust('deleteSkill', { name: skillSelectedName });
}

window.app.onSkillDeleted = function (jsonStr) {
  let data = {};
  try { data = JSON.parse(jsonStr); } catch (e) {}
  if (data.batch) {
    const failed = Array.isArray(data.failed) ? data.failed : [];
    if (failed.length) {
      const first = failed[0] || {};
      window.app.showToast('已删除 ' + (data.deleted_count || 0) + ' 个，' +
        failed.length + ' 个失败：' + (first.error || first.name || '未知原因'), 'error');
    } else {
      window.app.showToast('已删除 ' + (data.deleted_count || 0) + ' 个技能', 'success');
    }
    const deletedNames = Array.isArray(data.names) ? data.names : [];
    if ((skillSelectedName && deletedNames.indexOf(skillSelectedName) >= 0) ||
        (skillOriginalName && deletedNames.indexOf(skillOriginalName) >= 0)) {
      startNewSkill();
    }
    sendToRust('listSkills', {});
    return;
  }
  window.app.showToast('技能已删除', 'success');
  startNewSkill();
  sendToRust('listSkills', {});
};

(function initSkillManagerEvents() {
  const list = document.getElementById('skillList');
  if (list) {
    list.addEventListener('click', ev => {
      const item = ev.target.closest ? ev.target.closest('.skill-list-item[data-name]') : null;
      if (!item) return;
      if (skillSelectMode) _toggleSkillSelection(item.getAttribute('data-name'));
      else selectSkill(item.getAttribute('data-name'));
    });
    list.addEventListener('keydown', ev => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      const item = ev.target.closest ? ev.target.closest('.skill-list-item[data-name]') : null;
      if (item && ev.target === item) {
        ev.preventDefault();
        if (skillSelectMode) _toggleSkillSelection(item.getAttribute('data-name'));
        else selectSkill(item.getAttribute('data-name'));
      }
    });
  }
  const content = document.getElementById('skillContent');
  if (content) content.addEventListener('input', _updateSkillStats);
})();
