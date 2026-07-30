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
