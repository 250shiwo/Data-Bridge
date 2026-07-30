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
