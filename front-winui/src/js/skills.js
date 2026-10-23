// ===== 技能管理：列表 / 搜索过滤 / 编辑 / AI 润色 / 保存 / 删除 =====
// 数据来自 Rust 桥（JS 不能直连后端）：
//   openSkillManager -> listSkills
//   点击某项       -> loadSkill
//   AI 润色        -> polishSkill（后端只返回草稿，不落盘）
//   保存/删除      -> saveSkill / deleteSkill（保存后后端立即 reload）

let skillSelectedName = '';   // 当前编辑的技能（新建时为空）
let skillCurrentSource = '';  // builtin / user
let skillAll = [];            // 最近一次从后端拿到的完整技能列表
let skillFilterSource = 'all';
let skillSearchQuery = '';

function openSkillManager() {
  const modal = document.getElementById('skillManagerModal');
  if (!modal) return;
  modal.classList.add('show');
  startNewSkill();
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
  skillCurrentSource = '';
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
  const haystack = [skill.name, skill.title, skill.description].join(' ').toLowerCase();
  return haystack.indexOf(skillSearchQuery) >= 0;
}

function _renderSkillListItems() {
  const box = document.getElementById('skillList');
  const count = document.getElementById('skillCount');
  if (!box) return;
  const filtered = skillAll.filter(_skillMatches);
  if (count) {
    count.textContent = filtered.length === skillAll.length
      ? skillAll.length + ' 个技能'
      : filtered.length + ' / ' + skillAll.length + ' 个技能';
  }
  if (!filtered.length) {
    const empty = skillAll.length
      ? '没有匹配的技能，换个关键词或来源筛选试试。'
      : '还没有技能。用右侧 AI 润色创建一个。';
    box.innerHTML = '<div class="skill-empty"><div class="skill-empty-icon">🧩</div><div>' + empty + '</div></div>';
    return;
  }
  box.innerHTML = filtered.map(s => {
    const isUser = s.source === 'user';
    const badge = isUser
      ? '<span class="skill-tag user">用户</span>'
      : '<span class="skill-tag">内置</span>';
    const override = s.overrides_builtin ? '<span class="skill-tag warn">覆盖内置</span>' : '';
    return '<div class="skill-list-item" data-name="' + escAttr(s.name) + '" role="button" tabindex="0">' +
      '<div class="skill-item-top">' + badge + override + '</div>' +
      '<div class="skill-item-name">' + escHtml(s.title || s.name) + '</div>' +
      '<div class="skill-item-slug">' + escHtml(s.name) + '</div>' +
      '<div class="skill-item-desc">' + escHtml(s.description || '暂无描述') + '</div>' +
      '<span class="skill-item-arrow" aria-hidden="true">›</span>' +
      '</div>';
  }).join('');
  if (skillSelectedName) highlightSkillItem(skillSelectedName);
}

// 技能列表（后端返回 {count, skills:[{name,title,description,source,overrides_builtin,...}]}）
window.app = window.app || {};
window.app.renderSkillList = function (jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { return; }
  skillAll = Array.isArray(data.skills) ? data.skills : [];
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
  skillSelectedName = name;
  highlightSkillItem(name);
  sendToRust('loadSkill', { name: name });
}

// 单个技能全文（{name, source, content, overrides_builtin?}）
window.app.renderSkillDetail = function (jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { return; }
  skillSelectedName = data.name || '';
  skillCurrentSource = data.source || '';
  const name = document.getElementById('skillName');
  const content = document.getElementById('skillContent');
  const badge = document.getElementById('skillSourceBadge');
  const del = document.getElementById('skillDeleteBtn');
  if (name) name.value = data.name || '';
  if (content) content.value = data.content || '';
  if (badge) {
    badge.textContent = data.source === 'user'
      ? (data.overrides_builtin ? '用户技能 · 覆盖内置' : '用户技能 · 可编辑')
      : '内置技能 · 保存会创建同名用户技能';
  }
  if (del) del.style.display = data.source === 'user' ? '' : 'none';
  const meta = _refreshSkillTagsFromContent(data.content || '');
  if (!meta.title) _setSkillEditorHeading(data.name || '技能', meta.description || '');
  _updateSkillStats();
  setSkillMeta(data.source === 'user' ? '可修改后保存，立即生效' : '可复制为同名用户技能来定制');
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
  skillCurrentSource = 'user';
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
  const name = ((document.getElementById('skillName') || {}).value || '').trim();
  const content = (document.getElementById('skillContent') || {}).value || '';
  if (!name || !content.trim()) {
    window.app.showToast('技能名和 SKILL.md 内容都不能为空', 'error');
    return;
  }
  if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
    window.app.showToast('技能名只能用小写字母、数字和连字符，且不能以连字符开头', 'error');
    return;
  }
  sendToRust('saveSkill', { name: name, content: content });
}

window.app.onSkillSaved = function (jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { data = {}; }
  const skill = data.skill || {};
  skillSelectedName = skill.name || skillSelectedName;
  skillCurrentSource = 'user';
  const badge = document.getElementById('skillSourceBadge');
  if (badge) badge.textContent = '用户技能 · 可编辑';
  const del = document.getElementById('skillDeleteBtn');
  if (del) del.style.display = '';
  _refreshSkillTagsFromContent((document.getElementById('skillContent') || {}).value || '');
  _updateSkillStats();
  setSkillMeta('已保存，下一次规划/生成就会用上');
  window.app.showToast('技能已保存', 'success');
  sendToRust('listSkills', {});
};

function deleteCurrentSkill() {
  if (!skillSelectedName) return;
  if (!window.confirm('确定删除技能「' + skillSelectedName + '」吗？' +
    '如果是覆盖内置的同名技能，删除后会自动恢复内置版本。')) return;
  sendToRust('deleteSkill', { name: skillSelectedName });
}

window.app.onSkillDeleted = function (jsonStr) {
  window.app.showToast('技能已删除', 'success');
  startNewSkill();
  sendToRust('listSkills', {});
};

(function initSkillManagerEvents() {
  const list = document.getElementById('skillList');
  if (list) {
    list.addEventListener('click', ev => {
      const item = ev.target.closest ? ev.target.closest('.skill-list-item[data-name]') : null;
      if (item) selectSkill(item.getAttribute('data-name'));
    });
    list.addEventListener('keydown', ev => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      const item = ev.target.closest ? ev.target.closest('.skill-list-item[data-name]') : null;
      if (item && ev.target === item) {
        ev.preventDefault();
        selectSkill(item.getAttribute('data-name'));
      }
    });
  }
  const content = document.getElementById('skillContent');
  if (content) content.addEventListener('input', _updateSkillStats);
})();
