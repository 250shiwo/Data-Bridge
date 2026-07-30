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
