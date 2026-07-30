# DataBridge Navicat 风格界面改版 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Web GUI 从「三顶部页 + 下拉导航」改成 Navicat 式「左侧对象树 + 右侧标签页」布局，纯前端重构，后端零改动。

**Architecture:** 重写 `index.html` 为 SPA 外壳（顶栏 / 左树 / 标签栏+内容区），原生 JS 自建树与标签管理器；行同步与整表同步逻辑分别从 browser.js / sync.js 迁移为专用单例标签；连接管理收进树右键 + 弹框。

**Tech Stack:** 原生 JS（IIFE + 全局命名空间）、Tabulator 6.3.1（本地 vendor，不变）、既有 FastAPI REST API（不变）。

**Spec:** `docs/superpowers/specs/2026-07-29-databridge-navicat-ui-design.md`

## Global Constraints

- **后端零改动**：不修改任何 `.py` 文件；`uv run pytest` 始终 41 passed。
- 原生 JS，不引入任何新依赖、不做网络下载；`vendor/` 保持 Tabulator 6.3.1。
- 注释一律中文；代码风格与 `api.js` 一致（IIFE、双空格缩进、单引号）。
- **防 XSS**：动态文本（连接别名、库表名、主键值等）只能经 `textContent`、`.value` 赋值或 `esc()` 插入；纯静态模板才允许 innerHTML。
- 所有 HTTP 请求走全局 `api(method, path, body)`；写操作确认走 `showConfirm(html, {requireProtected})`，请求体带 `confirm: true`（护栏最终由服务层强制）。
- 全局命名空间（跨文件接口，名字必须逐字一致）：`esc` / `Tabs` / `Tree` / `ConnDialog` / `TabData` / `RowSync` / `TableSync`。
- 工作分支 `feature/navicat-ui`（Task 1 创建）；每任务一个 commit。
- 每任务验证：对本任务改动的每个 js 文件跑 `node --check`，输出必须为空；Task 1 与 Task 7 另跑全量 pytest。

## 全局接口一览（各任务实现者必须对齐）

| 提供方 | 接口 |
|---|---|
| util.js | `esc(v) -> string` HTML 转义 |
| tabs.js | `Tabs.open(key, title, build, onClose?)`（key 去重，已存在则激活；`build(panelEl)` 只在首建时调用）/ `Tabs.close(key)` / `Tabs.activate(key)` / `Tabs.has(key)` |
| tab-data.js | `TabData.open(alias, db, table)`；`TabData.fetchColumns(alias, db, table) -> Promise<columns>`（columns 即 `/api/browse` 返回的 `columns` 数组）；`TabData.buildGrid(el, ref, columns, withSelection) -> Tabulator`（ref={alias,db,table}；withSelection=true 时带勾选列且 index=__pk） |
| dlg-connection.js | `ConnDialog.openNew()` / `ConnDialog.openEdit(conn)`（conn 为 `/api/connections` 列表项） |
| tree.js | `Tree.init(el)` / `Tree.refreshConnections()` |
| tab-rowsync.js | `RowSync.setSource(alias, db, table)` / `RowSync.setTarget(alias, db, table)` |
| tab-tablesync.js | `TableSync.openWithSource(alias, db, table)` |

---

### Task 1: SPA 外壳（index.html 重写 + util.js + layout.js + 占位文件）

**Files:**
- Modify: `databridge/web/static/index.html`（整体重写）
- Create: `databridge/web/static/js/util.js`
- Create: `databridge/web/static/js/layout.js`
- Create（空占位，防 script 404）: `databridge/web/static/js/tabs.js`、`js/tree.js`、`js/dlg-connection.js`、`js/tab-data.js`、`js/tab-rowsync.js`、`js/tab-tablesync.js`

**Interfaces:**
- Consumes: 无
- Produces: 外壳 DOM（`#sidebar` `#splitter` `#tabbar` `#tabpanels` `#tab-empty` `#ctxmenu` `#btn-new-conn` `#toast` `#modal-mask/#modal`）；`esc()`；layout.js 入口（调 `Tree.init` 与 `ConnDialog.openNew`）

- [ ] **Step 1: 建分支**

```bash
git checkout -b feature/navicat-ui
```

- [ ] **Step 2: 重写 index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>DataBridge - MySQL 数据同步</title>
<link rel="stylesheet" href="/vendor/tabulator.min.css">
<style>
  * { box-sizing: border-box; }
  body { font-family: "Microsoft YaHei", sans-serif; margin: 0; background: #f5f6f8;
         height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
  header { background: #1f2937; color: #fff; padding: 8px 16px; display: flex;
           gap: 16px; align-items: center; flex: none; }
  header h1 { font-size: 17px; margin: 0 20px 0 0; }
  button.btn { padding: 6px 14px; border: none; border-radius: 5px; background: #2563eb;
               color: #fff; cursor: pointer; font-size: 13px; }
  button.btn.gray { background: #6b7280; }
  button.btn.red { background: #dc2626; }
  button.btn:disabled { opacity: .5; cursor: not-allowed; }
  input, select { padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 5px; font-size: 13px; }
  label { font-size: 13px; margin-right: 4px; }
  /* 主体三区 */
  #main { flex: 1; display: flex; min-height: 0; }
  #sidebar { width: 260px; min-width: 160px; max-width: 520px; background: #fff;
             border-right: 1px solid #e5e7eb; overflow: auto; padding: 6px 0; flex: none; }
  #splitter { width: 4px; cursor: col-resize; flex: none; }
  #splitter:hover { background: #93c5fd; }
  #right { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  /* 标签栏 */
  #tabbar { display: flex; background: #e5e7eb; border-bottom: 1px solid #d1d5db;
            overflow-x: auto; flex: none; }
  .tab-btn { display: flex; align-items: center; gap: 6px; padding: 7px 14px;
             font-size: 13px; cursor: pointer; border-right: 1px solid #d1d5db;
             white-space: nowrap; color: #374151; }
  .tab-btn.active { background: #fff; color: #111827; font-weight: bold; }
  .tab-btn .tab-x { color: #9ca3af; padding: 0 2px; }
  .tab-btn .tab-x:hover { color: #dc2626; }
  #tabpanels { flex: 1; overflow: auto; padding: 12px; min-height: 0; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  #tab-empty { color: #9ca3af; text-align: center; margin-top: 15vh; font-size: 14px; }
  /* 对象树 */
  .tnode-row { display: flex; align-items: center; gap: 4px; padding: 3px 8px;
               font-size: 13px; cursor: pointer; white-space: nowrap; user-select: none; }
  .tnode-row:hover { background: #f3f4f6; }
  .tnode-children { padding-left: 16px; }
  .tnode-err { color: #dc2626; font-size: 12px; padding: 2px 8px 2px 28px; cursor: pointer; }
  /* 右键菜单 */
  #ctxmenu { position: fixed; z-index: 950; background: #fff; border: 1px solid #d1d5db;
             border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,.15); display: none;
             min-width: 170px; padding: 4px 0; }
  #ctxmenu div { padding: 7px 14px; font-size: 13px; cursor: pointer; }
  #ctxmenu div:hover { background: #f3f4f6; }
  /* 卡片 / 表格 / toast / modal（沿用原风格） */
  .card { background: #fff; border-radius: 8px; padding: 14px; margin-bottom: 14px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  table.plain { border-collapse: collapse; width: 100%; font-size: 13px; }
  table.plain th, table.plain td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; }
  .grid-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  .selinfo { font-size: 12px; color: #2563eb; }
  #toast { position: fixed; top: 16px; right: 16px; z-index: 999; }
  .toast-item { background: #16a34a; color: #fff; padding: 10px 16px; border-radius: 6px;
                margin-bottom: 8px; font-size: 13px; }
  .toast-item.err { background: #dc2626; }
  #modal-mask { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 900; }
  #modal { background: #fff; border-radius: 8px; max-width: 560px; margin: 10vh auto;
           padding: 18px; max-height: 70vh; overflow: auto; }
</style>
</head>
<body>
<header>
  <h1>DataBridge</h1>
  <button class="btn" id="btn-new-conn">新建连接</button>
</header>
<div id="main">
  <div id="sidebar"></div>
  <div id="splitter"></div>
  <div id="right">
    <div id="tabbar"></div>
    <div id="tabpanels"><div id="tab-empty">双击左侧表打开数据</div></div>
  </div>
</div>
<div id="ctxmenu"></div>
<div id="toast"></div>
<div id="modal-mask"><div id="modal"></div></div>
<script src="/vendor/tabulator.min.js"></script>
<script src="/js/api.js"></script>
<script src="/js/util.js"></script>
<script src="/js/tabs.js"></script>
<script src="/js/dlg-connection.js"></script>
<script src="/js/tab-data.js"></script>
<script src="/js/tab-rowsync.js"></script>
<script src="/js/tab-tablesync.js"></script>
<script src="/js/tree.js"></script>
<script src="/js/layout.js"></script>
</body>
</html>
```

- [ ] **Step 3: 写 util.js**

```javascript
// 通用小工具：HTML 转义（动态文本插入 innerHTML 前必须过 esc）
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
```

- [ ] **Step 4: 写 layout.js**

```javascript
// 外壳入口：左栏拖拽调宽 + 模块初始化（脚本最后加载）
(function () {
  const sidebar = document.getElementById('sidebar');
  document.getElementById('splitter').onmousedown = e => {
    e.preventDefault();
    const startX = e.clientX, startW = sidebar.offsetWidth;
    const move = ev => {
      sidebar.style.width = Math.min(520, Math.max(160, startW + ev.clientX - startX)) + 'px';
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  };
  document.getElementById('btn-new-conn').onclick = () => ConnDialog.openNew();
  Tree.init(sidebar);
})();
```

- [ ] **Step 5: 建 6 个空占位 js 文件**

`tabs.js` / `tree.js` / `dlg-connection.js` / `tab-data.js` / `tab-rowsync.js` / `tab-tablesync.js` 各写入一行中文占位注释，如 `// 标签管理器（Task 2 实现）`。

- [ ] **Step 6: 验证**

Run: `node --check databridge/web/static/js/util.js` 和对 `layout.js` 同样执行
Expected: 无输出（语法通过）
Run: `uv run pytest -q`
Expected: `41 passed`（后端未动）

- [ ] **Step 7: Commit**

```bash
git add databridge/web/static
git commit -m "feat: Navicat 布局外壳（左树+标签页骨架 + util/layout）"
```

---

### Task 2: tabs.js 标签管理器

**Files:**
- Modify: `databridge/web/static/js/tabs.js`（占位 → 全部内容）

**Interfaces:**
- Consumes: 外壳 DOM `#tabbar` `#tabpanels` `#tab-empty`（Task 1）
- Produces: `Tabs.open(key, title, build, onClose?)` / `Tabs.close(key)` / `Tabs.activate(key)` / `Tabs.has(key)`

- [ ] **Step 1: 写 tabs.js**

```javascript
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
```

- [ ] **Step 2: 验证**

Run: `node --check databridge/web/static/js/tabs.js`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add databridge/web/static/js/tabs.js
git commit -m "feat: 标签管理器（key 去重/激活/关闭/空态）"
```

---

### Task 3: tab-data.js 单表浏览标签（含可复用网格构造器）

**Files:**
- Modify: `databridge/web/static/js/tab-data.js`（占位 → 全部内容）

**Interfaces:**
- Consumes: `Tabs.open`（Task 2）、全局 `api`
- Produces: `TabData.open(alias, db, table)`；`TabData.fetchColumns(alias, db, table)`；`TabData.buildGrid(el, ref, columns, withSelection)`（行同步标签复用，withSelection=true 时带勾选列、index='__pk'、跨页勾选持久）

- [ ] **Step 1: 写 tab-data.js**

```javascript
// 单表浏览标签：纯浏览（分页/列筛选/排序），无勾选。
// buildGrid/fetchColumns 同时供行同步标签复用。
const TabData = (function () {
  // 数字类型列 headerFilter 用等值，其余用 like（与后端 contains 对应）
  const NUMERIC = new Set(['int', 'bigint', 'smallint', 'tinyint', 'decimal',
                           'float', 'double', 'mediumint']);

  async function fetchColumns(alias, db, table) {
    // 取第一页只为拿列元数据（/api/browse 响应含 columns）
    const first = await api('POST', '/api/browse', {
      alias, db, table, page: 1, page_size: 1 });
    return first.columns;
  }

  function buildGrid(el, ref, columns, withSelection) {
    const pkCols = columns.filter(c => c.is_pk).map(c => c.name);
    const colDefs = [];
    if (withSelection) {
      colDefs.push({ formatter: 'rowSelection', titleFormatter: 'rowSelection',
                     hozAlign: 'center', headerSort: false, width: 44 });
    }
    columns.forEach(c => colDefs.push({
      title: c.name + (c.is_pk ? ' 🔑' : ''), field: c.name,
      headerFilter: 'input',
      headerFilterFunc: NUMERIC.has(c.type) ? '=' : 'like',
    }));
    const opts = {
      height: 480, layout: 'fitDataStretch', index: '__pk',
      pagination: true, paginationMode: 'remote', paginationSize: 50,
      paginationSizeSelector: [20, 50, 100],
      sortMode: 'remote', filterMode: 'remote',
      ajaxURL: '/api/browse',   // 占位，实际请求由 ajaxRequestFunc 发出
      ajaxRequestFunc: async (url, config, params) => {
        const filters = (params.filter || []).map(f => ({
          column: f.field,
          op: f.type === 'like' ? 'contains' : 'eq',
          value: f.value,
        }));
        const sort = (params.sort || [])[0];
        const out = await api('POST', '/api/browse', {
          alias: ref.alias, db: ref.db, table: ref.table,
          page: params.page || 1, page_size: params.size || 50,
          filters, sort_column: sort ? sort.field : null,
          sort_dir: sort ? sort.dir : 'asc',
        });
        out.rows.forEach(r => {
          // 无主键表用整行值兜底（仅浏览场景；行同步在装载时已拦截无主键表）
          r.__pk = pkCols.length ? JSON.stringify(pkCols.map(k => r[k]))
                                 : JSON.stringify(Object.values(r));
        });
        return { last_page: Math.max(1, Math.ceil(out.total / (params.size || 50))),
                 data: out.rows };
      },
      columns: colDefs,
    };
    if (withSelection) {
      opts.selectableRows = true;
      opts.selectableRowsPersistence = true;   // 跨页保持勾选（Tabulator 6.x）
    }
    return new Tabulator(el, opts);
  }

  function open(alias, db, table) {
    const key = alias + '/' + db + '/' + table;
    let grid = null;
    Tabs.open(key, db + '.' + table, async panel => {
      const card = document.createElement('div');
      card.className = 'card';
      const bar = document.createElement('div');
      bar.className = 'grid-toolbar';
      const btn = document.createElement('button');
      btn.className = 'btn gray';
      btn.textContent = '刷新';
      bar.appendChild(btn);
      const gridEl = document.createElement('div');
      card.append(bar, gridEl);
      panel.appendChild(card);
      const columns = await fetchColumns(alias, db, table);
      grid = buildGrid(gridEl, { alias, db, table }, columns, false);
      btn.onclick = () => grid.setData();
    }, () => { if (grid) grid.destroy(); });
  }

  return { open, fetchColumns, buildGrid };
})();
```

- [ ] **Step 2: 验证**

Run: `node --check databridge/web/static/js/tab-data.js`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add databridge/web/static/js/tab-data.js
git commit -m "feat: 单表浏览标签 + 可复用远程网格构造器"
```

---

### Task 4: dlg-connection.js 连接对话框

**Files:**
- Modify: `databridge/web/static/js/dlg-connection.js`（占位 → 全部内容）

**Interfaces:**
- Consumes: `#modal-mask/#modal`（Task 1）、全局 `api/toast/invalidateConnections`、`Tree.refreshConnections()`（Task 5 提供，运行时才调用，加载顺序无碍）
- Produces: `ConnDialog.openNew()` / `ConnDialog.openEdit(conn)`（conn 为 `/api/connections` 列表项，无密码）

- [ ] **Step 1: 写 dlg-connection.js**

```javascript
// 连接对话框：新建 / 编辑（别名只读）/ 测试连接；复用 #modal 弹层
const ConnDialog = (function () {
  function openDialog(conn) {
    const mask = document.getElementById('modal-mask');
    const modal = document.getElementById('modal');
    const isEdit = !!conn;
    // 模板为纯静态内容，动态值一律走 .value / .checked 赋值（防 XSS）
    modal.innerHTML = `
      <h3>${isEdit ? '编辑连接' : '新增连接'}</h3>
      <div class="grid-toolbar">
        <label>别名 <input id="cd-alias" ${isEdit ? 'readonly style="background:#f3f4f6"' : ''}></label>
        <label>主机 <input id="cd-host"></label>
        <label>端口 <input id="cd-port" type="number" value="3306" style="width:70px"></label>
      </div>
      <div class="grid-toolbar">
        <label>用户 <input id="cd-user"></label>
        <label>密码 <input id="cd-pass" type="password" placeholder="${isEdit ? '留空=不修改' : ''}"></label>
        <label>默认库 <input id="cd-db" placeholder="可选"></label>
        <label><input id="cd-prot" type="checkbox"> 受保护</label>
      </div>
      <div style="margin-top:12px;text-align:right">
        <button class="btn gray" id="cd-test">测试连接</button>
        <button class="btn gray" id="cd-cancel">取消</button>
        <button class="btn" id="cd-save">保存</button>
      </div>`;
    if (conn) {
      modal.querySelector('#cd-alias').value = conn.alias;
      modal.querySelector('#cd-host').value = conn.host;
      modal.querySelector('#cd-port').value = conn.port;
      modal.querySelector('#cd-user').value = conn.user;
      modal.querySelector('#cd-db').value = conn.default_db || '';
      modal.querySelector('#cd-prot').checked = !!conn.protected;
    }
    mask.style.display = 'block';
    const close = () => { mask.style.display = 'none'; };
    const body = () => ({
      alias: modal.querySelector('#cd-alias').value.trim(),
      host: modal.querySelector('#cd-host').value.trim(),
      port: parseInt(modal.querySelector('#cd-port').value, 10) || 3306,
      user: modal.querySelector('#cd-user').value.trim(),
      password: modal.querySelector('#cd-pass').value,   // 编辑留空=保留旧密码（后端语义）
      default_db: modal.querySelector('#cd-db').value.trim() || null,
      protected: modal.querySelector('#cd-prot').checked,
    });
    modal.querySelector('#cd-cancel').onclick = close;
    modal.querySelector('#cd-test').onclick = async () => {
      const b = body();
      if (!b.alias || !b.host || !b.user) { toast('别名/主机/用户必填', true); return; }
      const out = await api('POST', '/api/connections/test', b);
      toast(out.ok ? '连接成功' : '连接失败', !out.ok);
    };
    modal.querySelector('#cd-save').onclick = async () => {
      const b = body();
      if (!b.alias || !b.host || !b.user) { toast('别名/主机/用户必填', true); return; }
      await api('POST', '/api/connections', b);
      toast('已保存');
      close();
      invalidateConnections();
      Tree.refreshConnections();
    };
  }
  return { openNew: () => openDialog(null), openEdit: c => openDialog(c) };
})();
```

- [ ] **Step 2: 验证**

Run: `node --check databridge/web/static/js/dlg-connection.js`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add databridge/web/static/js/dlg-connection.js
git commit -m "feat: 连接对话框（新建/编辑别名只读/测试/空密码保留）"
```

---

### Task 5: tree.js 对象树 + 右键菜单

**Files:**
- Modify: `databridge/web/static/js/tree.js`（占位 → 全部内容）

**Interfaces:**
- Consumes: `#ctxmenu`（Task 1）、`api/toast/showConfirm/loadConnections/invalidateConnections/esc`、`ConnDialog`（Task 4）、`TabData.open`（Task 3）、`RowSync.setSource/setTarget`（Task 6，运行时才调用）、`TableSync.openWithSource`（Task 7，运行时才调用）
- Produces: `Tree.init(el)` / `Tree.refreshConnections()`

- [ ] **Step 1: 写 tree.js**

```javascript
// 对象树：连接 → 库 → 表，懒加载展开 + 右键菜单 + 失败就地重试
const Tree = (function () {
  let rootEl = null;

  // ---------- 右键菜单（原生自绘，点击他处消失） ----------
  function showMenu(x, y, items) {
    const m = document.getElementById('ctxmenu');
    m.innerHTML = '';
    items.forEach(it => {
      const d = document.createElement('div');
      d.textContent = it.label;                 // 动态文本走 textContent
      d.onclick = () => { hideMenu(); it.action(); };
      m.appendChild(d);
    });
    m.style.left = x + 'px';
    m.style.top = y + 'px';
    m.style.display = 'block';
  }
  function hideMenu() { document.getElementById('ctxmenu').style.display = 'none'; }
  document.addEventListener('click', hideMenu);

  // ---------- 通用懒加载节点 ----------
  // loadChildren(childrenEl) 为 null 表示叶子；menuItems(ctx) 返回右键项数组
  function makeNode(parentEl, indent, icon, text, loadChildren, menuItems, onDblClick) {
    const row = document.createElement('div');
    row.className = 'tnode-row';
    row.style.paddingLeft = (8 + indent * 14) + 'px';
    const arrow = document.createElement('span');
    arrow.textContent = loadChildren ? '▸' : '·';
    const label = document.createElement('span');
    label.textContent = icon + ' ' + text;
    row.append(arrow, label);
    const childrenEl = document.createElement('div');
    childrenEl.className = 'tnode-children';
    childrenEl.style.display = 'none';
    parentEl.append(row, childrenEl);
    let loaded = false, open = false;
    async function expand(force) {
      if (!loadChildren) return;
      if (force) loaded = false;
      if (!loaded) {
        arrow.textContent = '…';
        childrenEl.innerHTML = '';
        try {
          await loadChildren(childrenEl);
          loaded = true;
        } catch (e) {
          // api() 已 toast；节点上留可重试入口，不拖垮整棵树
          childrenEl.innerHTML = '';
          const err = document.createElement('div');
          err.className = 'tnode-err';
          err.textContent = '加载失败，点击重试';
          err.onclick = () => expand(true);
          childrenEl.appendChild(err);
        }
      }
      open = true;
      childrenEl.style.display = '';
      arrow.textContent = '▾';
    }
    function collapse() { open = false; childrenEl.style.display = 'none'; arrow.textContent = '▸'; }
    row.onclick = () => { open ? collapse() : expand(false); };
    if (onDblClick) row.ondblclick = onDblClick;
    row.oncontextmenu = e => {
      e.preventDefault();
      e.stopPropagation();
      if (menuItems) showMenu(e.clientX, e.clientY, menuItems({ refresh: () => expand(true) }));
    };
  }

  // ---------- 三层节点 ----------
  function addTableNode(el, conn, db, table) {
    makeNode(el, 2, '▤', table, null, () => [
      { label: '打开表', action: () => TabData.open(conn.alias, db, table) },
      { label: '设为同步源', action: () => RowSync.setSource(conn.alias, db, table) },
      { label: '设为同步目标', action: () => RowSync.setTarget(conn.alias, db, table) },
      { label: '整表同步（以此为源）…', action: () => TableSync.openWithSource(conn.alias, db, table) },
    ], () => TabData.open(conn.alias, db, table));
  }

  function addDbNode(el, conn, db) {
    makeNode(el, 1, '🗀', db, async childrenEl => {
      const tbls = await api('GET', '/api/tables?alias=' +
        encodeURIComponent(conn.alias) + '&db=' + encodeURIComponent(db));
      tbls.forEach(t => addTableNode(childrenEl, conn, db, t));
    }, ctx => [{ label: '刷新表列表', action: ctx.refresh }]);
  }

  function addConnNode(el, conn) {
    makeNode(el, 0, '🖧', conn.alias + (conn.protected ? ' 🔒' : ''), async childrenEl => {
      const dbs = await api('GET', '/api/databases?alias=' + encodeURIComponent(conn.alias));
      dbs.forEach(db => addDbNode(childrenEl, conn, db));
    }, ctx => [
      { label: '编辑连接…', action: () => ConnDialog.openEdit(conn) },
      { label: '测试连接', action: () => testConn(conn) },
      { label: '删除连接', action: () => delConn(conn) },
      { label: '刷新库列表', action: ctx.refresh },
    ]);
  }

  async function testConn(conn) {
    // 密码留空：后端会用已存密码回填（/api/connections/test 语义）
    const out = await api('POST', '/api/connections/test', {
      alias: conn.alias, host: conn.host, port: conn.port, user: conn.user,
      password: '', default_db: conn.default_db, protected: conn.protected });
    toast(out.ok ? '连接成功' : '连接失败', !out.ok);
  }

  async function delConn(conn) {
    if (!await showConfirm(`删除连接 <b>${esc(conn.alias)}</b>？`)) return;
    await api('DELETE', '/api/connections/' + encodeURIComponent(conn.alias));
    toast('已删除');
    refreshConnections();
  }

  async function refreshConnections() {
    invalidateConnections();
    const list = await loadConnections();
    rootEl.innerHTML = '';
    if (!list.length) {
      const tip = document.createElement('div');
      tip.className = 'tnode-err';
      tip.textContent = '暂无连接，点击顶栏「新建连接」';
      rootEl.appendChild(tip);
      return;
    }
    list.forEach(c => addConnNode(rootEl, c));
  }

  function init(el) {
    rootEl = el;
    el.oncontextmenu = e => {
      e.preventDefault();
      showMenu(e.clientX, e.clientY, [{ label: '新建连接…', action: () => ConnDialog.openNew() }]);
    };
    refreshConnections();
  }

  return { init, refreshConnections };
})();
```

- [ ] **Step 2: 验证**

Run: `node --check databridge/web/static/js/tree.js`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add databridge/web/static/js/tree.js
git commit -m "feat: 对象树（懒加载/失败重试/右键菜单/连接入口）"
```

---

### Task 6: tab-rowsync.js 行同步标签

**Files:**
- Modify: `databridge/web/static/js/tab-rowsync.js`（占位 → 全部内容）

**Interfaces:**
- Consumes: `Tabs.open`（Task 2）、`TabData.fetchColumns/buildGrid`（Task 3）、`api/toast/showConfirm/loadConnections/esc`
- Produces: `RowSync.setSource(alias, db, table)` / `RowSync.setTarget(alias, db, table)`

- [ ] **Step 1: 写 tab-rowsync.js**

```javascript
// 行同步标签（单例）：上源下目标双网格 + 勾选行新增/替换。
// 相比旧版修复：操作成功后清空勾选、请求期间禁用按钮、操作后刷新目标网格。
const RowSync = (function () {
  const KEY = '__rowsync__';
  const sides = { src: null, dst: null };   // 每侧: {ref, grid, selOrder, pkCols}
  let panel = null;

  function ensureTab() {
    Tabs.open(KEY, '行同步', p => {
      panel = p;
      p.innerHTML = `
        <div class="card">
          <div class="grid-toolbar"><b>源表：</b><span data-role="src-name">未装载，从左树右键「设为同步源」</span>
            <span class="selinfo" data-role="src-sel"></span>
            <button class="btn gray" data-role="src-clear" style="display:none">清空勾选</button></div>
          <div data-role="src-grid"></div>
        </div>
        <div class="card" style="text-align:center">
          <button class="btn" data-role="btn-insert">⬇ 新增到目标（追加，自增主键由目标分配）</button>
          <button class="btn red" data-role="btn-replace">⬇ 替换目标勾选行（N对N按勾选顺序）</button>
        </div>
        <div class="card">
          <div class="grid-toolbar"><b>目标表：</b><span data-role="dst-name">未装载，从左树右键「设为同步目标」</span>
            <span class="selinfo" data-role="dst-sel"></span>
            <button class="btn gray" data-role="dst-clear" style="display:none">清空勾选</button></div>
          <div data-role="dst-grid"></div>
        </div>`;
      q('btn-insert').onclick = doInsert;
      q('btn-replace').onclick = doReplace;
      q('src-clear').onclick = () => clearSel('src');
      q('dst-clear').onclick = () => clearSel('dst');
    }, () => {
      for (const k of ['src', 'dst']) {
        if (sides[k] && sides[k].grid) sides[k].grid.destroy();
        sides[k] = null;
      }
      panel = null;
    });
  }

  function q(role) { return panel.querySelector('[data-role=' + role + ']'); }

  function updateSel(name) {
    q(name + '-sel').textContent = sides[name] ? '已勾选 ' + sides[name].selOrder.length + ' 行' : '';
  }

  function clearSel(name) {
    const s = sides[name];
    if (!s) return;
    s.selOrder = [];
    s.grid.deselectRow();
    updateSel(name);
  }

  async function load(name, alias, db, table) {
    ensureTab();
    const columns = await TabData.fetchColumns(alias, db, table);
    const pkCols = columns.filter(c => c.is_pk).map(c => c.name);
    if (!pkCols.length) { toast('该表无主键，不支持勾选同步', true); return; }
    if (sides[name] && sides[name].grid) sides[name].grid.destroy();
    const gridEl = q(name + '-grid');
    gridEl.innerHTML = '';
    const side = { ref: { alias, db, table }, selOrder: [], pkCols, grid: null };
    side.grid = TabData.buildGrid(gridEl, side.ref, columns, true);
    side.grid.on('rowSelected', row => {
      const pk = row.getIndex();
      if (!side.selOrder.includes(pk)) side.selOrder.push(pk);   // 记忆勾选顺序
      updateSel(name);
    });
    side.grid.on('rowDeselected', row => {
      side.selOrder = side.selOrder.filter(k => k !== row.getIndex());
      updateSel(name);
    });
    sides[name] = side;
    q(name + '-name').textContent = alias + ' / ' + db + ' / ' + table;
    q(name + '-clear').style.display = '';
    updateSel(name);
  }

  function pkValues(side) { return side.selOrder.map(s => JSON.parse(s)); }

  async function isProtected(alias) {
    const list = await loadConnections();
    const c = list.find(x => x.alias === alias);
    return c ? c.protected : false;
  }

  function setBusy(busy) {
    q('btn-insert').disabled = busy;
    q('btn-replace').disabled = busy;
  }

  // ---------- 新增（追加） ----------
  async function doInsert() {
    const s = sides.src, d = sides.dst;
    if (!s || !d) { toast('请先从左树装载源表和目标表', true); return; }
    if (!s.selOrder.length) { toast('请先在源表勾选行', true); return; }
    const prot = await isProtected(d.ref.alias);
    const ok = await showConfirm(
      `将源表勾选的 <b>${s.selOrder.length}</b> 行追加到目标
       <b>${esc(d.ref.alias)} / ${esc(d.ref.db)} / ${esc(d.ref.table)}</b><br>
       自增主键由目标表自动分配。`, { requireProtected: prot });
    if (!ok) return;
    setBusy(true);
    try {
      const out = await api('POST', '/api/rows/insert', {
        src: s.ref, dst: d.ref, pk_values: pkValues(s), confirm: true });
      toast('新增成功：' + out.inserted + ' 行');
      clearSel('src');          // 追加不是幂等操作：成功后必须清空防重复
      d.grid.setData();
    } finally { setBusy(false); }
  }

  // ---------- 替换（N对N按序） ----------
  async function doReplace() {
    const s = sides.src, d = sides.dst;
    if (!s || !d) { toast('请先从左树装载源表和目标表', true); return; }
    if (s.selOrder.length === 0 || s.selOrder.length !== d.selOrder.length) {
      toast(`源已勾 ${s.selOrder.length} 行 / 目标已勾 ${d.selOrder.length} 行，数量必须相等且大于 0`, true);
      return;
    }
    const pairs = s.selOrder.map((v, i) =>
      `<tr><td>${esc(v)}</td><td>→</td><td>${esc(d.selOrder[i])}</td></tr>`).join('');
    const prot = await isProtected(d.ref.alias);
    const ok = await showConfirm(
      `替换目标 <b>${esc(d.ref.alias)} / ${esc(d.ref.db)} / ${esc(d.ref.table)}</b> 的
       <b>${d.selOrder.length}</b> 行（目标主键保留，其余列被源行覆盖）：
       <table class="plain"><tr><th>源主键</th><th></th><th>目标主键</th></tr>${pairs}</table>`,
      { requireProtected: prot });
    if (!ok) return;
    setBusy(true);
    try {
      const out = await api('POST', '/api/rows/replace', {
        src: s.ref, dst: d.ref,
        src_pk_values: pkValues(s), dst_pk_values: pkValues(d), confirm: true });
      toast('替换成功：' + out.replaced + ' 行');
      clearSel('src');
      clearSel('dst');
      d.grid.setData();
    } finally { setBusy(false); }
  }

  return {
    setSource: (a, db, t) => load('src', a, db, t),
    setTarget: (a, db, t) => load('dst', a, db, t),
  };
})();
```

- [ ] **Step 2: 验证**

Run: `node --check databridge/web/static/js/tab-rowsync.js`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add databridge/web/static/js/tab-rowsync.js
git commit -m "feat: 行同步标签（双网格勾选新增/替换 + 成功清勾选/请求禁用按钮）"
```

---

### Task 7: tab-tablesync.js 整表同步标签 + 删旧文件 + 全量回归

**Files:**
- Modify: `databridge/web/static/js/tab-tablesync.js`（占位 → 全部内容）
- Delete: `databridge/web/static/js/connections.js`、`databridge/web/static/js/browser.js`、`databridge/web/static/js/sync.js`

**Interfaces:**
- Consumes: `Tabs.open`（Task 2）、`api/toast/showConfirm/loadConnections/esc`
- Produces: `TableSync.openWithSource(alias, db, table)`

- [ ] **Step 1: 写 tab-tablesync.js**

```javascript
// 整表同步标签（单例）：源侧树预填只读，目标侧级联下拉；预览(dry-run)→执行(upsert)。
// 相比旧版修复：切换连接清空下级下拉、请求期间禁用按钮。
const TableSync = (function () {
  const KEY = '__tablesync__';
  let panel = null;
  const state = { src: null };              // {alias,db,table}
  const dst = { alias: '', db: '' };

  function q(role) { return panel.querySelector('[data-role=' + role + ']'); }

  function build(p) {
    panel = p;
    p.innerHTML = `
      <div class="card">
        <h3>整表增量同步（按主键比对，新增+覆盖，不删除）</h3>
        <div class="grid-toolbar"><b>源：</b><span data-role="s-name">未选择，从左树右键「整表同步（以此为源）」</span></div>
        <div class="grid-toolbar"><b>目标：</b>
          <label>连接 <select data-role="d-conn"><option value="">选择</option></select></label>
          <label>库 <select data-role="d-db"></select></label>
          <label>表 <select data-role="d-tbl"></select></label></div>
        <div class="grid-toolbar">
          <label>WHERE（可选，仅限定源表范围） <input data-role="d-where" style="width:320px"
            placeholder="如 id > 100 AND status = 'A'"></label></div>
        <button class="btn gray" data-role="d-preview">预览差异（不写数据）</button>
        <button class="btn" data-role="d-exec">执行同步</button>
        <div class="card" data-role="d-result" style="display:none"></div>
      </div>`;
    loadConnections().then(list => {
      list.forEach(c => q('d-conn').add(new Option(c.alias, c.alias)));
    });
    q('d-conn').onchange = async e => {
      dst.alias = e.target.value;
      dst.db = '';
      q('d-db').innerHTML = '';
      q('d-tbl').innerHTML = '';            // 切换连接先清空下级，防止旧库表残留错配
      if (!dst.alias) return;
      const dbs = await api('GET', '/api/databases?alias=' + encodeURIComponent(dst.alias));
      dbs.forEach(d => q('d-db').add(new Option(d, d)));
      q('d-db').onchange();
    };
    q('d-db').onchange = async () => {
      dst.db = q('d-db').value;
      q('d-tbl').innerHTML = '';
      if (!dst.db) return;
      const tbls = await api('GET', '/api/tables?alias=' +
        encodeURIComponent(dst.alias) + '&db=' + encodeURIComponent(dst.db));
      tbls.forEach(t => q('d-tbl').add(new Option(t, t)));
    };
    q('d-preview').onclick = () => run(false);
    q('d-exec').onclick = () => run(true);
  }

  function body() {
    if (!state.src) { toast('请先从左树选择源表', true); return null; }
    const tbl = q('d-tbl').value;
    if (!dst.alias || !dst.db || !tbl) { toast('请选择完整的目标 连接/库/表', true); return null; }
    return {
      src: state.src,
      dst: { alias: dst.alias, db: dst.db, table: tbl },
      where: q('d-where').value.trim() || null,
    };
  }

  function showResult(html) {
    const el = q('d-result');
    el.style.display = 'block';
    el.innerHTML = html;                    // 拼入前动态值已全部 esc
  }

  async function run(exec) {
    const b = body();
    if (!b) return;
    q('d-preview').disabled = true;
    q('d-exec').disabled = true;
    try {
      if (!exec) {
        const out = await api('POST', '/api/sync/preview', b);
        showResult(`<b>预览结果（未写入任何数据）</b><br>
          将新增：${out.to_insert} 行，将覆盖：${out.to_update} 行<br>
          主键示例：${esc(JSON.stringify(out.sample_pks))}`);
      } else {
        const list = await loadConnections();
        const prot = (list.find(c => c.alias === b.dst.alias) || {}).protected;
        const ok = await showConfirm(
          `将 <b>${esc(b.src.alias)}/${esc(b.src.db)}/${esc(b.src.table)}</b> 增量同步到
           <b>${esc(b.dst.alias)}/${esc(b.dst.db)}/${esc(b.dst.table)}</b><br>
           冲突策略：同主键覆盖（upsert）；不删除目标多余行。`,
          { requireProtected: !!prot });
        if (!ok) return;
        const t0 = Date.now();
        const out = await api('POST', '/api/sync/execute', Object.assign({ confirm: true }, b));
        showResult(`<b>同步完成</b><br>
          新增：${out.inserted} 行，覆盖：${out.updated} 行，
          耗时：${((Date.now() - t0) / 1000).toFixed(1)}s`);
        toast('同步完成');
      }
    } finally {
      q('d-preview').disabled = false;
      q('d-exec').disabled = false;
    }
  }

  function openWithSource(alias, db, table) {
    Tabs.open(KEY, '整表同步', build, () => { panel = null; state.src = null; });
    state.src = { alias, db, table };
    q('s-name').textContent = alias + ' / ' + db + ' / ' + table;
  }

  return { openWithSource };
})();
```

- [ ] **Step 2: 删除旧文件**

```bash
git rm databridge/web/static/js/connections.js databridge/web/static/js/browser.js databridge/web/static/js/sync.js
```

- [ ] **Step 3: 全量验证**

对 `databridge/web/static/js/` 下全部 8 个 js 文件（util/layout/tabs/tree/dlg-connection/tab-data/tab-rowsync/tab-tablesync）逐个跑 `node --check`
Expected: 全部无输出
Run: `uv run pytest -q`
Expected: `41 passed`（后端未动）
确认 `index.html` 无任何指向已删除文件的 `<script>` 引用（Task 1 已重写，应为 0 处）。

- [ ] **Step 4: Commit**

```bash
git add -A databridge/web/static
git commit -m "feat: 整表同步标签 + 移除旧三页前端（Navicat 改版收口）"
```

---

## 任务依赖关系

```
Task 1 (外壳+util+layout+占位)
  └─ Task 2 (tabs 标签管理器)
       └─ Task 3 (tab-data 单表浏览+网格构造器)
            ├─ Task 4 (dlg-connection 连接对话框)
            ├─ Task 6 (tab-rowsync 行同步，复用 Task 3 网格)
            └─ Task 7 (tab-tablesync 整表同步+删旧文件)
       Task 5 (tree 对象树) 依赖 Task 3/4 接口名（运行时调用 Task 6/7 接口）
```

执行顺序：1 → 2 → 3 → 4 → 5 → 6 → 7。

## 验收对照（spec §8）

| 验收项 | 对应任务 |
|---|---|
| 树懒加载/失败重试/刷新 | Task 5 |
| 标签去重/切换保态/关闭销毁/空态 | Task 2 |
| 单表浏览（无主键也可浏览） | Task 3 |
| 行同步全流程 + 三项修复 | Task 6 |
| 整表同步 + 两项修复 | Task 7 |
| 连接对话框（别名只读/空密码） | Task 4 |
| 防 XSS（esc/textContent） | 全任务约束 |
| 后端 41 测试保绿 | Task 1、7 验证步骤 |
