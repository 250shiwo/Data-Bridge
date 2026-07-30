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
