// ===== 输入框与发送逻辑 =====
function useSuggestion(type) {
  const prompts = { csv: '分析这份销售数据，按季度生成趋势折线图', excel: '对比多个 Excel 表格的产品类别表现', db: '连接数据库，分析用户注册趋势', pdf: '从 PDF 报表中提取表格数据并可视化' };
  const input = document.getElementById('prompt-input');
  hideChatCommandMenu();
  input.value = prompts[type] || '';
  autoResize(input);
  input.focus();
}

// ===== 聊天命令：输入 / 打开命令菜单，/skill 打开技能选择器 =====
const CHAT_COMMANDS = [
  { id: 'skill', icon: '🧩', label: '加载技能', desc: '选择一个场景技能带入本次对话', keys: '/skill', keywords: 'skill 技能 加载 场景' },
  { id: 'skill-manager', icon: '⚙️', label: '管理技能', desc: '打开技能管理，新建 / 编辑 / 删除技能', keys: '/skills', keywords: 'skills 技能 技能管理 管理 编辑 删除' },
  { id: 'clear', icon: '⌫', label: '清空输入', desc: '清空当前输入框内容', keys: '/clear', keywords: 'clear 清空 重置' },
];

let _chatCommands = [];
let _chatCommandIndex = 0;
let _chatCommandOpen = false;

function handleChatInput(el) {
  autoResize(el);
  updateChatCommandMenu(el ? el.value : '');
}

function hideChatCommandMenu() {
  _chatCommandOpen = false;
  _chatCommands = [];
  _chatCommandIndex = 0;
  const menu = document.getElementById('chatCommandMenu');
  if (menu) {
    menu.classList.remove('show');
    menu.innerHTML = '';
  }
  const input = document.getElementById('prompt-input');
  if (input) {
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-controls');
  }
}

function _renderChatCommandMenu(items) {
  const menu = document.getElementById('chatCommandMenu');
  if (!menu) return;
  _chatCommands = items;
  if (_chatCommandIndex >= items.length) _chatCommandIndex = 0;
  menu.innerHTML = items.map((cmd, idx) => {
    const active = idx === _chatCommandIndex;
    return '<button type="button" class="chat-command-item' + (active ? ' active' : '') + '" role="option" aria-selected="' + (active ? 'true' : 'false') + '" data-command="' + escAttr(cmd.id) + '">' +
      '<span class="chat-command-icon" aria-hidden="true">' + escHtml(cmd.icon) + '</span>' +
      '<span class="chat-command-main"><span class="chat-command-title">' + escHtml(cmd.label) + '</span>' +
      '<span class="chat-command-desc">' + escHtml(cmd.desc) + '</span></span>' +
      '<span class="chat-command-key">' + escHtml(cmd.keys) + '</span>' +
      '</button>';
  }).join('');
  menu.classList.add('show');
  _chatCommandOpen = true;
  const input = document.getElementById('prompt-input');
  if (input) {
    input.setAttribute('aria-expanded', 'true');
    input.setAttribute('aria-controls', 'chatCommandMenu');
  }
}

function updateChatCommandMenu(value) {
  const leading = String(value || '').replace(/^\s+/, '');
  if (!leading.startsWith('/')) { hideChatCommandMenu(); return; }
  const body = leading.slice(1);
  if (/\s/.test(body)) { hideChatCommandMenu(); return; }
  const query = body.toLowerCase();
  const items = CHAT_COMMANDS.filter(cmd => {
    if (!query) return true;
    return (cmd.label + ' ' + cmd.desc + ' ' + cmd.keys + ' ' + cmd.keywords).toLowerCase().indexOf(query) >= 0;
  });
  if (!items.length) { hideChatCommandMenu(); return; }
  _chatCommandIndex = 0;
  _renderChatCommandMenu(items);
}

function _moveChatCommand(delta) {
  if (!_chatCommands.length) return;
  _chatCommandIndex = (_chatCommandIndex + delta + _chatCommands.length) % _chatCommands.length;
  document.querySelectorAll('#chatCommandMenu .chat-command-item').forEach((el, idx) => {
    const active = idx === _chatCommandIndex;
    el.classList.toggle('active', active);
    el.setAttribute('aria-selected', active ? 'true' : 'false');
  });
}

function runChatCommand(id) {
  const input = document.getElementById('prompt-input');
  hideChatCommandMenu();
  if (id === 'skill') {
    if (input) { input.value = ''; autoResize(input); }
    openSkillPicker();
    return;
  }
  if (id === 'skill-manager') {
    if (input) { input.value = ''; autoResize(input); }
    openSkillManager();
    return;
  }
  if (id === 'clear') {
    if (input) {
      input.value = '';
      autoResize(input);
      input.focus();
    }
  }
}

function runActiveChatCommand() {
  const cmd = _chatCommands[_chatCommandIndex];
  if (cmd) runChatCommand(cmd.id);
}

// ===== 已加载技能：输入区 chip + 发送时拼到 prompt 前 =====
function setActiveSkill(skill) {
  if (!skill || !skill.name) return;
  if (state.optimizeTarget) {
    state.optimizeTarget = null;
    renderOptimizeChip();
  }
  state.activeSkill = {
    name: skill.name,
    title: skill.title || skill.name,
    description: skill.description || '',
    chartTypes: Array.isArray(skill.chart_types) ? skill.chart_types.slice() : [],
    analysisTasks: Array.isArray(skill.analysis_tasks) ? skill.analysis_tasks.slice() : [],
    userKeywords: Array.isArray(skill.user_keywords) ? skill.user_keywords.slice() : [],
    requireKeywords: !!skill.require_keywords,
    source: skill.source || '',
  };
  renderSkillChip();
}

function clearActiveSkill() {
  state.activeSkill = null;
  renderSkillChip();
}

function renderSkillChip() {
  const chip = document.getElementById('skillChip');
  const label = document.getElementById('skillChipLabel');
  if (!chip || !label) return;
  const skill = state.activeSkill;
  if (!skill) {
    chip.style.display = 'none';
    label.textContent = '';
    label.removeAttribute('title');
    label.removeAttribute('data-tip');
    return;
  }
  label.textContent = '技能：' + skill.title;
  label.setAttribute('data-tip', skill.title + '（' + skill.name + '）');
  chip.style.display = 'flex';
}

function _skillPromptDirective(skill) {
  const bits = ['请优先使用技能「' + skill.title + '」（name: ' + skill.name + '）中的分析口径和图表规范。'];
  if (skill.description) bits.push('技能用途：' + skill.description + '。');
  if (skill.chartTypes && skill.chartTypes.length) bits.push('推荐图表：' + skill.chartTypes.join(' / ') + '。');
  if (skill.analysisTasks && skill.analysisTasks.length) bits.push('分析任务：' + skill.analysisTasks.join(' / ') + '。');
  if (skill.userKeywords && skill.userKeywords.length) bits.push('场景关键词：' + skill.userKeywords.join('、') + '。');
  return bits.join('') + '\n';
}

function selectMode(el, mode) {
  document.querySelectorAll('.mode-chip[data-mode]').forEach(c => {
    c.classList.remove('active');
    c.setAttribute('aria-pressed', 'false');
  });
  el.classList.add('active');
  el.setAttribute('aria-pressed', 'true');
  state.vizMode = mode;
}

function toggleMultiTable() {
  state.multiTable = !state.multiTable;
  const chip = document.getElementById('multi-table-chip');
  if (chip) {
    chip.classList.toggle('active', state.multiTable);
    chip.setAttribute('aria-pressed', state.multiTable ? 'true' : 'false');
  }
}

// ===== 二次优化：选中某张已生成的图，输入区进入优化模式 =====
function setOptimizeTarget(chartId, title) {
  state.optimizeTarget = { chartId: chartId, title: title || chartId };
  clearActiveSkill();
  renderOptimizeChip();
  const input = document.getElementById('prompt-input');
  if (input) {
    input.value = '优化“' + (title || chartId) + '”：';
    if (typeof autoResize === 'function') autoResize(input);
    input.focus();
    if (input.scrollIntoView) input.scrollIntoView({ block: 'nearest' });
  }
}

function clearOptimizeTarget() {
  state.optimizeTarget = null;
  renderOptimizeChip();
}

function renderOptimizeChip() {
  const chip = document.getElementById('optimizeChip');
  const label = document.getElementById('optimizeChipLabel');
  if (!chip || !label) return;
  if (state.optimizeTarget) {
    label.textContent = '优化：' + state.optimizeTarget.title + '（只改图形，不重跑数据）';
    chip.style.display = 'flex';
  } else {
    chip.style.display = 'none';
    label.textContent = '';
  }
}

function sendPrompt() {
  const input = document.getElementById('prompt-input');
  const basePrompt = input.value.trim();
  if (!basePrompt || state.isGenerating) return;
  // 点击发送按钮时也识别聊天命令，避免把 /skill 当普通提示词发出去。
  const textCommand = basePrompt.toLowerCase();
  const matchedCommand = CHAT_COMMANDS.filter(cmd => cmd.keys === textCommand || ('/' + cmd.id) === textCommand)[0];
  if (matchedCommand) {
    input.value = '';
    autoResize(input);
    runChatCommand(matchedCommand.id);
    return;
  }
  const skillArg = basePrompt.match(/^\/(?:skill|技能)\s+(.+)$/i);
  if (skillArg) {
    input.value = '';
    autoResize(input);
    openSkillPicker(skillArg[1].trim());
    return;
  }
  const optimizeTarget = state.optimizeTarget;
  const activeSkill = state.activeSkill;
  if (optimizeTarget) clearOptimizeTarget();
  const prompt = activeSkill ? _skillPromptDirective(activeSkill) + basePrompt : basePrompt;
  const filesToSend = state.files.filter(f => typeof f === 'string');
  // 保留本次输入的数据源，供“补充说明并重试”恢复，不必重新选文件
  state.lastFiles = state.files.map(f => (typeof f === 'object' ? { ...f } : f));
  // 渲染用户消息（含文件标签）
  hideWelcome();
  const userMsg = document.createElement('div');
  userMsg.className = 'msg user';
  let fileHtml = '';
  if (state.files.length > 0) {
    fileHtml = '<div class="msg-files">' + state.files.map(f => {
      const isObj = typeof f === 'object';
      const name = isObj ? f.name : (f.split(/[\\/]/).pop() || f);
      const icon = isObj && f.isDb ? '🗄️' : '📄';
      return '<div class="msg-file">' + icon + ' ' + escHtml(name) + '</div>';
    }).join('') + '</div>';
  }
  const content = document.createElement('div');
  content.className = 'msg-content';
  let bubbleText;
  if (optimizeTarget) bubbleText = '🛠 优化《' + optimizeTarget.title + '》：' + basePrompt;
  else if (activeSkill) bubbleText = '🧩 使用技能：' + activeSkill.title + '\n' + basePrompt;
  else bubbleText = basePrompt;
  content.innerHTML = '<div class="msg-name">你</div><div class="msg-bubble"></div>' + fileHtml;
  content.querySelector('.msg-bubble').textContent = bubbleText;
  userMsg.innerHTML = '<div class="msg-avatar user">K</div>';
  userMsg.appendChild(content);
  document.getElementById('chatInner').appendChild(userMsg);
  // 清空输入、技能和文件
  input.value = '';
  input.style.height = 'auto';
  state.files = [];
  state.activeSkill = null;
  renderSkillChip();
  renderFileChips();
  // 发送到 Rust
  if (optimizeTarget) {
    sendToRust('optimizeChart', { chartId: optimizeTarget.chartId, prompt: prompt });
  } else if (state.mode === 'code') {
    sendToRust('completeCode', { prompt: prompt, files: filesToSend });
  } else {
    sendToRust('sendPrompt', { prompt: prompt, files: filesToSend, vizMode: state.vizMode, multiTable: state.multiTable, dbConfig: state.selectedDb, apiConfig: state.apiConfig || null, config: state.config || null });
  }
  scrollToBottom({ force: true });
}

function cancelTask() { sendToRust('cancelTask', {}); }

function newChat() {
  state.files = [];
  state.lastFiles = [];
  state.selectedDb = null;
  state.apiConfig = null;
  state.optimizeTarget = null;
  state.activeSkill = null;
  renderOptimizeChip();
  renderSkillChip();
  renderFileChips();
  hideChatCommandMenu();
  sendToRust('newChat', {});
}

function handleInputKey(e) {
  // 中文输入法组词中按 Enter 是“上屏”，不能当成发送
  if (e.isComposing || e.keyCode === 229) return;

  if (_chatCommandOpen) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      _moveChatCommand(e.key === 'ArrowDown' ? 1 : -1);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      hideChatCommandMenu();
      return;
    }
    if (e.key === 'Tab') {
      hideChatCommandMenu();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      runActiveChatCommand();
      return;
    }
  }

  // 支持 /skill 关键词：直接带着搜索词打开技能选择器
  if (e.key === 'Enter' && !e.shiftKey) {
    const input = document.getElementById('prompt-input');
    const match = input && input.value.match(/^\/(?:skill|技能)\s+(.+)$/i);
    if (match) {
      e.preventDefault();
      input.value = '';
      autoResize(input);
      openSkillPicker(match[1].trim());
      return;
    }
    e.preventDefault();
    sendPrompt();
  }
}

// 自动撑高输入框：逐字触发时合并到一帧内完成，避免每按一键都强制同步布局
const _resizeTargets = new Set();
let _resizeScheduled = false;

function autoResize(el) {
  if (!el) return;
  _resizeTargets.add(el);
  if (_resizeScheduled) return;
  _resizeScheduled = true;
  requestAnimationFrame(() => {
    _resizeScheduled = false;
    _resizeTargets.forEach(target => {
      target.style.height = 'auto';
      target.style.height = Math.min(target.scrollHeight, 120) + 'px';
    });
    _resizeTargets.clear();
  });
}

(function initChatCommandMenu() {
  const menu = document.getElementById('chatCommandMenu');
  if (menu) {
    menu.addEventListener('click', ev => {
      const item = ev.target.closest ? ev.target.closest('[data-command]') : null;
      if (item) runChatCommand(item.getAttribute('data-command'));
    });
  }
  document.addEventListener('pointerdown', ev => {
    if (!_chatCommandOpen) return;
    const current = document.getElementById('chatCommandMenu');
    const input = document.getElementById('prompt-input');
    if (current && current.contains(ev.target)) return;
    if (input && input === ev.target) return;
    hideChatCommandMenu();
  });
})();
