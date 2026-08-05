// ===== 工具函数 =====
function scrollToBottom() {
  const el = document.getElementById('chatMessages');
  setTimeout(() => { if (el) el.scrollTop = el.scrollHeight; }, 50);
}

function nowStr() {
  const d = new Date();
  return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0') + ':' + d.getSeconds().toString().padStart(2,'0');
}

function escHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escAttr(s) {
  if (s == null) return '';
  return String(s).replace(/\\/g,'\\\\').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ===== 拖拽上传 =====
const inputBox = document.getElementById('chatInputBox');
if (inputBox) {
  inputBox.addEventListener('dragover', e => { e.preventDefault(); inputBox.classList.add('dragover'); });
  inputBox.addEventListener('dragleave', () => inputBox.classList.remove('dragover'));
  inputBox.addEventListener('drop', e => {
    e.preventDefault(); inputBox.classList.remove('dragover');
    window.app.showToast('请使用附件按钮选择文件', 'info');
  });
}

// ===== 初始化 =====
sendToRust('loadHistory', {});
