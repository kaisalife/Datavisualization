// ===== 技能管理：列表 / 编辑 / AI 润色 / 保存 / 删除 =====
// 数据来自 Rust 桥（JS 不能直连后端）：
//   openSkillManager -> listSkills
//   点击某项       -> loadSkill
//   AI 润色        -> polishSkill（后端只返回草稿，不落盘）
//   保存/删除      -> saveSkill / deleteSkill（保存后后端立即 reload）

let skillSelectedName = '';   // 当前编辑的技能（新建时为空）
let skillCurrentSource = '';  // builtin / user

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
  setSkillMeta('技能名即目录名；保存后立即生效');
  highlightSkillItem('');
}

function highlightSkillItem(name) {
  document.querySelectorAll('.skill-list-item').forEach(el => {
    el.classList.toggle('active', el.getAttribute('data-name') === name);
  });
}

// 技能列表（后端返回 {count, skills:[{name,title,description,source,overrides_builtin,...}]}）
window.app = window.app || {};
window.app.renderSkillList = function (jsonStr) {
  const box = document.getElementById('skillList');
  if (!box) return;
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { return; }
  const skills = Array.isArray(data.skills) ? data.skills : [];

  if (!skills.length) {
    box.innerHTML = '<div class="skill-empty">还没有技能。用右侧 AI 润色创建一个。</div>';
    return;
  }

  box.innerHTML = skills.map(s => {
    const isUser = s.source === 'user';
    const badge = isUser
      ? '<span class="skill-tag user">用户</span>'
      : '<span class="skill-tag">内置</span>';
    const override = s.overrides_builtin ? '<span class="skill-tag warn">覆盖内置</span>' : '';
    return '<div class="skill-list-item" data-name="' + escAttr(s.name) + '" onclick="selectSkill(\'' + escAttr(s.name) + '\')">' +
      '<div class="skill-item-top">' + badge + override + '</div>' +
      '<div class="skill-item-name">' + escHtml(s.title || s.name) + '</div>' +
      '<div class="skill-item-desc">' + escHtml(s.description || '') + '</div>' +
      '</div>';
  }).join('');

  if (skillSelectedName) highlightSkillItem(skillSelectedName);
};

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
      ? (data.overrides_builtin ? '用户技能（覆盖内置）' : '用户技能，可编辑')
      : '内置技能（只读；保存会创建同名用户技能覆盖它）';
  }
  if (del) del.style.display = data.source === 'user' ? '' : 'none';
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
  if (btn) { btn.disabled = true; btn.textContent = '润色中...'; }
  setSkillMeta('AI 正在写技能，可能需要几十秒...');
  sendToRust('polishSkill', { prompt: prompt, name: name.trim() });
}

window.app.onSkillPolished = function (jsonStr) {
  const btn = document.getElementById('skillPolishBtn');
  if (btn) { btn.disabled = false; btn.textContent = 'AI 润色'; }
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { return; }
  const content = document.getElementById('skillContent');
  const name = document.getElementById('skillName');
  if (content) content.value = data.content || '';
  if (name && !name.value.trim() && data.skill && data.skill.name) {
    name.value = data.skill.name;
  }
  const skill = data.skill || {};
  setSkillMeta('草稿已生成：' + (skill.title || skill.name || '') +
    (skill.chart_types && skill.chart_types.length ? ' · ' + skill.chart_types.join('/') : '') +
    ' · 确认无误后点「保存技能」');
  window.app.showToast('AI 草稿已生成，请确认后保存', 'success');
};

function saveCurrentSkill() {
  const name = ((document.getElementById('skillName') || {}).value || '').trim();
  const content = (document.getElementById('skillContent') || {}).value || '';
  if (!name || !content.trim()) {
    window.app.showToast('技能名和 SKILL.md 内容都不能为空', 'error');
    return;
  }
  sendToRust('saveSkill', { name: name, content: content });
}

window.app.onSkillSaved = function (jsonStr) {
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { data = {}; }
  const skill = data.skill || {};
  skillSelectedName = skill.name || skillSelectedName;
  const badge = document.getElementById('skillSourceBadge');
  if (badge) badge.textContent = '用户技能，可编辑';
  const del = document.getElementById('skillDeleteBtn');
  if (del) del.style.display = '';
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
  let data;
  try { data = JSON.parse(jsonStr); } catch (e) { data = {}; }
  window.app.showToast('技能已删除', 'success');
  startNewSkill();
  sendToRust('listSkills', {});
};
