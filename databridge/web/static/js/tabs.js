// 标签管理器：按 key 去重打开/激活/关闭；隐藏而非销毁，切回不丢状态
const Tabs = (function () {
  const tabs = new Map();   // key -> {btn, panel, onClose}

  function updateEmpty() {
    document.getElementById('tab-empty').style.display = tabs.size ? 'none' : 'block';
  }

  function activate(key) {
    tabs.forEach((t, k) => {
      t.btn.classList.toggle('active', k === key);
      t.panel.classList.toggle('active', k === key);
    });
    updateEmpty();
  }

  function open(key, title, build, onClose) {
    if (tabs.has(key)) { activate(key); return tabs.get(key); }
    const btn = document.createElement('div');
    btn.className = 'tab-btn';
    const label = document.createElement('span');
    label.textContent = title;                  // 动态标题走 textContent 防 XSS
    const x = document.createElement('span');
    x.className = 'tab-x';
    x.textContent = '×';
    btn.append(label, x);
    btn.onclick = () => activate(key);
    x.onclick = e => { e.stopPropagation(); close(key); };
    document.getElementById('tabbar').appendChild(btn);
    const panel = document.createElement('div');
    panel.className = 'tab-panel';
    document.getElementById('tabpanels').appendChild(panel);
    const tab = { btn, panel, onClose };
    tabs.set(key, tab);
    build(panel);                               // 只在首建时渲染一次
    activate(key);
    return tab;
  }

  function close(key) {
    const t = tabs.get(key);
    if (!t) return;
    if (t.onClose) t.onClose();                 // 由调用方销毁 Tabulator 等资源
    t.btn.remove();
    t.panel.remove();
    tabs.delete(key);
    const last = [...tabs.keys()].pop();
    if (last) activate(last); else updateEmpty();
  }

  return { open, close, activate, has: k => tabs.has(k) };
})();
