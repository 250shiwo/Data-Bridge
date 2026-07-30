// 单表浏览标签：分页/列筛选/排序；有主键表带勾选，勾选后可直接「追加到…/替换到…」。
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

  // 追加目标选择弹框：级联选 连接/库/表，确认后把勾选行追加过去
  function openAppendDialog(ref, selOrder, onDone) {
    const mask = document.getElementById('modal-mask');
    const modal = document.getElementById('modal');
    const dst = { alias: '', db: '' };
    // 模板纯静态；selOrder.length 为数字，下拉项经 Option 构造器插入（防 XSS）
    modal.innerHTML = `
      <h3>追加到目标表</h3>
      <p style="font-size:13px">已勾选 <b>${selOrder.length}</b> 行，自增主键由目标表分配。</p>
      <div class="grid-toolbar">
        <label>连接 <select id="ad-conn"><option value="">选择</option></select></label>
        <label>库 <select id="ad-db"></select></label>
        <label>表 <select id="ad-tbl"></select></label>
      </div>
      <div style="margin-top:12px;text-align:right">
        <button class="btn gray" id="ad-cancel">取消</button>
        <button class="btn" id="ad-ok">追加</button>
      </div>`;
    mask.style.display = 'block';
    const close = () => { mask.style.display = 'none'; };
    loadConnections().then(list => {
      list.forEach(c => modal.querySelector('#ad-conn').add(new Option(c.alias, c.alias)));
    });
    modal.querySelector('#ad-conn').onchange = async e => {
      dst.alias = e.target.value;
      dst.db = '';
      modal.querySelector('#ad-db').innerHTML = '';
      modal.querySelector('#ad-tbl').innerHTML = '';   // 切换连接先清空下级，防旧库表残留
      if (!dst.alias) return;
      const dbs = await api('GET', '/api/databases?alias=' + encodeURIComponent(dst.alias));
      dbs.forEach(d => modal.querySelector('#ad-db').add(new Option(d, d)));
      modal.querySelector('#ad-db').onchange();
    };
    modal.querySelector('#ad-db').onchange = async () => {
      dst.db = modal.querySelector('#ad-db').value;
      modal.querySelector('#ad-tbl').innerHTML = '';
      if (!dst.db) return;
      const tbls = await api('GET', '/api/tables?alias=' +
        encodeURIComponent(dst.alias) + '&db=' + encodeURIComponent(dst.db));
      tbls.forEach(t => modal.querySelector('#ad-tbl').add(new Option(t, t)));
    };
    modal.querySelector('#ad-cancel').onclick = close;
    modal.querySelector('#ad-ok').onclick = async () => {
      const tbl = modal.querySelector('#ad-tbl').value;
      if (!dst.alias || !dst.db || !tbl) { toast('请选择完整的目标 连接/库/表', true); return; }
      const list = await loadConnections();
      const prot = (list.find(c => c.alias === dst.alias) || {}).protected;
      close();
      const ok = await showConfirm(
        `将 <b>${selOrder.length}</b> 行追加到目标
         <b>${esc(dst.alias)} / ${esc(dst.db)} / ${esc(tbl)}</b><br>自增主键由目标表自动分配。`,
        { requireProtected: !!prot });
      if (!ok) return;
      const out = await api('POST', '/api/rows/insert', {
        src: ref, dst: { alias: dst.alias, db: dst.db, table: tbl },
        pk_values: selOrder.map(s => JSON.parse(s)), confirm: true });
      toast('追加成功：' + out.inserted + ' 行');
      onDone();                                 // 追加非幂等：成功后清空勾选防重复
    };
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
      const selInfo = document.createElement('span');
      selInfo.className = 'selinfo';
      const btnAppend = document.createElement('button');
      btnAppend.className = 'btn';
      btnAppend.textContent = '追加到…';
      btnAppend.style.display = 'none';
      const btnReplace = document.createElement('button');
      btnReplace.className = 'btn red';
      btnReplace.textContent = '替换到…';
      btnReplace.style.display = 'none';
      bar.append(btn, selInfo, btnAppend, btnReplace);
      const gridEl = document.createElement('div');
      card.append(bar, gridEl);
      panel.appendChild(card);
      const columns = await fetchColumns(alias, db, table);
      const hasPk = columns.some(c => c.is_pk);   // 无主键表不给勾选入口（同步会被拦截）
      let selOrder = [];                          // 勾选顺序（__pk），与行同步标签同语义
      grid = buildGrid(gridEl, { alias, db, table }, columns, hasPk);
      const updateSel = () => {
        selInfo.textContent = selOrder.length ? '已勾选 ' + selOrder.length + ' 行' : '';
        const show = selOrder.length ? '' : 'none';
        btnAppend.style.display = show;
        btnReplace.style.display = show;
      };
      if (hasPk) {
        grid.on('rowSelected', row => {
          const pk = row.getIndex();
          if (!selOrder.includes(pk)) selOrder.push(pk);   // 记忆勾选顺序
          updateSel();
        });
        grid.on('rowDeselected', row => {
          selOrder = selOrder.filter(k => k !== row.getIndex());
          updateSel();
        });
      }
      btn.onclick = () => grid.setData();
      btnAppend.onclick = () => openAppendDialog({ alias, db, table }, selOrder, () => {
        selOrder = [];
        grid.deselectRow();
        updateSel();
      });
      btnReplace.onclick = () => {
        // 带着勾选跳到行同步标签：当前表装为源，去目标侧勾等量行
        RowSync.setSource(alias, db, table, selOrder.slice());
        toast('已装载为同步源，请在目标侧勾选相同数量的行');
      };
    }, () => { if (grid) grid.destroy(); });
  }

  return { open, fetchColumns, buildGrid };
})();
