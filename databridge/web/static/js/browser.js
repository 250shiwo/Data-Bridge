// 数据浏览器：源/目标双网格，勾选行新增(追加)/替换(N对N按序)
(function () {
  const root = document.getElementById('tab-browser');
  root.innerHTML = `
    <div class="card" id="panel-src"><h3>源表</h3></div>
    <div class="card" style="text-align:center">
      <button class="btn" id="btn-insert">⬇ 新增到目标（追加，自增主键由目标分配）</button>
      <button class="btn red" id="btn-replace">⬇ 替换目标勾选行（N对N按勾选顺序）</button>
    </div>
    <div class="card" id="panel-dst"><h3>目标表</h3></div>`;

  // ---------- 面板：连接/库/表选择 + Tabulator 网格 ----------
  function createPanel(el, name) {
    const panel = { el, name, table: null, columns: [], pkCols: [],
                    selOrder: [], alias: '', db: '', tbl: '' };
    const bar = document.createElement('div');
    bar.className = 'grid-toolbar';
    bar.innerHTML = `
      <label>连接 <select class="sel-conn"><option value="">选择</option></select></label>
      <label>库 <select class="sel-db"></select></label>
      <label>表 <select class="sel-tbl"></select></label>
      <button class="btn gray b-load">加载</button>
      <span class="selinfo">已勾选 0 行</span>
      <button class="btn gray b-clear">清空勾选</button>`;
    el.appendChild(bar);
    const gridEl = document.createElement('div');
    el.appendChild(gridEl);
    panel.gridEl = gridEl;
    panel.bar = bar;

    loadConnections().then(list => {
      const sel = bar.querySelector('.sel-conn');
      list.forEach(c => sel.add(new Option(c.alias, c.alias)));
    });
    bar.querySelector('.sel-conn').onchange = async e => {
      panel.alias = e.target.value;
      const dbs = await api('GET', '/api/databases?alias=' + encodeURIComponent(panel.alias));
      const sel = bar.querySelector('.sel-db');
      sel.innerHTML = '';
      dbs.forEach(d => sel.add(new Option(d, d)));
      sel.onchange();
    };
    bar.querySelector('.sel-db').onchange = async () => {
      panel.db = bar.querySelector('.sel-db').value;
      if (!panel.db) return;
      const tbls = await api('GET', '/api/tables?alias=' +
        encodeURIComponent(panel.alias) + '&db=' + encodeURIComponent(panel.db));
      const sel = bar.querySelector('.sel-tbl');
      sel.innerHTML = '';
      tbls.forEach(t => sel.add(new Option(t, t)));
    };
    bar.querySelector('.b-load').onclick = () => loadGrid(panel);
    bar.querySelector('.b-clear').onclick = () => {
      panel.selOrder = [];
      if (panel.table) panel.table.deselectRow();
      updateSelInfo(panel);
    };
    return panel;
  }

  function updateSelInfo(panel) {
    panel.bar.querySelector('.selinfo').textContent =
      '已勾选 ' + panel.selOrder.length + ' 行';
  }

  // headerFilter 类型映射：字符串列 contains，其它 eq
  const NUMERIC = new Set(['int', 'bigint', 'smallint', 'tinyint', 'decimal',
                           'float', 'double', 'mediumint']);

  async function loadGrid(panel) {
    panel.tbl = panel.bar.querySelector('.sel-tbl').value;
    if (!panel.alias || !panel.db || !panel.tbl) { toast('请先选择连接/库/表', true); return; }
    // 先取第一页拿列元数据
    const first = await api('POST', '/api/browse', {
      alias: panel.alias, db: panel.db, table: panel.tbl, page: 1, page_size: 50 });
    panel.columns = first.columns;
    panel.pkCols = first.columns.filter(c => c.is_pk).map(c => c.name);
    if (!panel.pkCols.length) { toast('该表无主键，不支持勾选同步', true); return; }
    panel.selOrder = [];
    updateSelInfo(panel);

    const colDefs = [{ formatter: 'rowSelection', titleFormatter: 'rowSelection',
                       hozAlign: 'center', headerSort: false, width: 44 }];
    panel.columns.forEach(c => colDefs.push({
      title: c.name + (c.is_pk ? ' 🔑' : ''), field: c.name,
      headerFilter: 'input',
      headerFilterFunc: NUMERIC.has(c.type) ? '=' : 'like',
    }));

    if (panel.table) panel.table.destroy();
    panel.table = new Tabulator(panel.gridEl, {
      height: 320, layout: 'fitDataStretch', index: '__pk',
      selectableRows: true, selectableRowsPersistence: true,
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
          alias: panel.alias, db: panel.db, table: panel.tbl,
          page: params.page || 1, page_size: params.size || 50,
          filters, sort_column: sort ? sort.field : null,
          sort_dir: sort ? sort.dir : 'asc',
        });
        out.rows.forEach(r => {
          r.__pk = JSON.stringify(panel.pkCols.map(k => r[k]));
        });
        return { last_page: Math.max(1, Math.ceil(out.total / (params.size || 50))),
                 data: out.rows };
      },
      columns: colDefs,
    });
    panel.table.on('rowSelected', row => {
      const pk = row.getIndex();
      if (!panel.selOrder.includes(pk)) panel.selOrder.push(pk);
      updateSelInfo(panel);
    });
    panel.table.on('rowDeselected', row => {
      panel.selOrder = panel.selOrder.filter(k => k !== row.getIndex());
      updateSelInfo(panel);
    });
  }

  const src = createPanel(document.getElementById('panel-src'), '源');
  const dst = createPanel(document.getElementById('panel-dst'), '目标');

  function ref(panel) {
    return { alias: panel.alias, db: panel.db, table: panel.tbl };
  }
  function pkValues(panel) {
    return panel.selOrder.map(s => JSON.parse(s));
  }
  async function isProtected(alias) {
    const list = await loadConnections();
    const c = list.find(x => x.alias === alias);
    return c ? c.protected : false;
  }
  function ready(panel) {
    if (!panel.table) { toast(panel.name + '表未加载', true); return false; }
    return true;
  }

  // ---------- 新增（追加） ----------
  document.getElementById('btn-insert').onclick = async () => {
    if (!ready(src) || !ready(dst)) return;
    if (!src.selOrder.length) { toast('请先在源表勾选行', true); return; }
    const prot = await isProtected(dst.alias);
    const ok = await showConfirm(
      `将源表勾选的 <b>${src.selOrder.length}</b> 行追加到目标
       <b>${dst.alias} / ${dst.db} / ${dst.tbl}</b><br>
       自增主键由目标表自动分配。`, { requireProtected: prot });
    if (!ok) return;
    const out = await api('POST', '/api/rows/insert', {
      src: ref(src), dst: ref(dst), pk_values: pkValues(src), confirm: true });
    toast('新增成功：' + out.inserted + ' 行');
    dst.table.setData();   // 刷新目标网格
  };

  // ---------- 替换（N对N按序） ----------
  document.getElementById('btn-replace').onclick = async () => {
    if (!ready(src) || !ready(dst)) return;
    if (src.selOrder.length === 0 || src.selOrder.length !== dst.selOrder.length) {
      toast(`源已勾 ${src.selOrder.length} 行 / 目标已勾 ${dst.selOrder.length} 行，数量必须相等且大于 0`, true);
      return;
    }
    // 配对预览表：源第 i 个勾选 -> 目标第 i 个勾选
    const pairs = src.selOrder.map((s, i) =>
      `<tr><td>${s}</td><td>→</td><td>${dst.selOrder[i]}</td></tr>`).join('');
    const prot = await isProtected(dst.alias);
    const ok = await showConfirm(
      `替换目标 <b>${dst.alias} / ${dst.db} / ${dst.tbl}</b> 的
       <b>${dst.selOrder.length}</b> 行（目标主键保留，其余列被源行覆盖）：
       <table class="plain"><tr><th>源主键</th><th></th><th>目标主键</th></tr>${pairs}</table>`,
      { requireProtected: prot });
    if (!ok) return;
    const out = await api('POST', '/api/rows/replace', {
      src: ref(src), dst: ref(dst),
      src_pk_values: pkValues(src), dst_pk_values: pkValues(dst), confirm: true });
    toast('替换成功：' + out.replaced + ' 行');
    dst.table.setData();
  };
})();
