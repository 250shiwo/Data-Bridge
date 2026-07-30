// 整表增量同步页：预览（dry-run）→ 执行（upsert）
(function () {
  const root = document.getElementById('tab-sync');
  root.innerHTML = `
    <div class="card">
      <h3>整表增量同步（按主键比对，新增+覆盖，不删除）</h3>
      <div class="grid-toolbar" id="s-src"><b>源：</b></div>
      <div class="grid-toolbar" id="s-dst"><b>目标：</b></div>
      <div class="grid-toolbar">
        <label>WHERE（可选，仅限定源表范围） <input id="s-where" style="width:320px"
          placeholder="如 id > 100 AND status = 'A'"></label>
      </div>
      <button class="btn gray" id="s-preview">预览差异（不写数据）</button>
      <button class="btn" id="s-exec">执行同步</button>
      <div class="card" id="s-result" style="display:none"></div>
    </div>`;

  // 一行连接/库/表选择器
  function selector(el) {
    const s = { alias: '', db: '', tbl: '' };
    el.insertAdjacentHTML('beforeend', `
      <label>连接 <select class="q-conn"><option value="">选择</option></select></label>
      <label>库 <select class="q-db"></select></label>
      <label>表 <select class="q-tbl"></select></label>`);
    loadConnections().then(list => {
      const sel = el.querySelector('.q-conn');
      list.forEach(c => sel.add(new Option(c.alias, c.alias)));
    });
    el.querySelector('.q-conn').onchange = async e => {
      s.alias = e.target.value;
      const dbs = await api('GET', '/api/databases?alias=' + encodeURIComponent(s.alias));
      const sel = el.querySelector('.q-db');
      sel.innerHTML = '';
      dbs.forEach(d => sel.add(new Option(d, d)));
      sel.onchange();
    };
    el.querySelector('.q-db').onchange = async () => {
      s.db = el.querySelector('.q-db').value;
      if (!s.db) return;
      const tbls = await api('GET', '/api/tables?alias=' +
        encodeURIComponent(s.alias) + '&db=' + encodeURIComponent(s.db));
      const sel = el.querySelector('.q-tbl');
      sel.innerHTML = '';
      tbls.forEach(t => sel.add(new Option(t, t)));
    };
    s.read = () => { s.tbl = el.querySelector('.q-tbl').value; return s; };
    return s;
  }

  const src = selector(document.getElementById('s-src'));
  const dst = selector(document.getElementById('s-dst'));

  function body() {
    src.read(); dst.read();
    if (!src.alias || !src.db || !src.tbl || !dst.alias || !dst.db || !dst.tbl) {
      toast('请选择完整的源/目标 连接/库/表', true);
      return null;
    }
    return {
      src: { alias: src.alias, db: src.db, table: src.tbl },
      dst: { alias: dst.alias, db: dst.db, table: dst.tbl },
      where: document.getElementById('s-where').value.trim() || null,
    };
  }

  function showResult(html) {
    const el = document.getElementById('s-result');
    el.style.display = 'block';
    el.innerHTML = html;
  }

  document.getElementById('s-preview').onclick = async () => {
    const b = body();
    if (!b) return;
    const out = await api('POST', '/api/sync/preview', b);
    showResult(`<b>预览结果（未写入任何数据）</b><br>
      将新增：${out.to_insert} 行，将覆盖：${out.to_update} 行<br>
      主键示例：${JSON.stringify(out.sample_pks)}`);
  };

  document.getElementById('s-exec').onclick = async () => {
    const b = body();
    if (!b) return;
    const list = await loadConnections();
    const prot = (list.find(c => c.alias === b.dst.alias) || {}).protected;
    const ok = await showConfirm(
      `将 <b>${b.src.alias}/${b.src.db}/${b.src.table}</b> 增量同步到
       <b>${b.dst.alias}/${b.dst.db}/${b.dst.table}</b><br>
       冲突策略：同主键覆盖（upsert）；不删除目标多余行。`,
      { requireProtected: !!prot });
    if (!ok) return;
    const t0 = Date.now();
    const out = await api('POST', '/api/sync/execute', Object.assign({ confirm: true }, b));
    showResult(`<b>同步完成</b><br>
      新增：${out.inserted} 行，覆盖：${out.updated} 行，
      耗时：${((Date.now() - t0) / 1000).toFixed(1)}s`);
    toast('同步完成');
  };
})();
