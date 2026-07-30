// 连接管理页：列表 + 表单（新增/编辑）+ 测试连接 + 删除
(function () {
  const root = document.getElementById('tab-connections');
  root.innerHTML = `
    <div class="card">
      <h3>连接列表</h3>
      <table class="plain" id="conn-table">
        <thead><tr><th>别名</th><th>主机</th><th>端口</th><th>用户</th>
        <th>默认库</th><th>受保护</th><th>操作</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="card">
      <h3 id="conn-form-title">新增连接</h3>
      <div class="grid-toolbar">
        <label>别名 <input id="c-alias"></label>
        <label>主机 <input id="c-host"></label>
        <label>端口 <input id="c-port" type="number" value="3306" style="width:70px"></label>
        <label>用户 <input id="c-user"></label>
        <label>密码 <input id="c-pass" type="password" placeholder="编辑时留空=不修改"></label>
        <label>默认库 <input id="c-db" placeholder="可选"></label>
        <label><input id="c-prot" type="checkbox"> 受保护</label>
      </div>
      <button class="btn" id="c-save">保存</button>
      <button class="btn gray" id="c-test">测试连接</button>
      <button class="btn gray" id="c-reset">清空</button>
    </div>`;

  function formBody() {
    return {
      alias: document.getElementById('c-alias').value.trim(),
      host: document.getElementById('c-host').value.trim(),
      port: parseInt(document.getElementById('c-port').value, 10) || 3306,
      user: document.getElementById('c-user').value.trim(),
      password: document.getElementById('c-pass').value,
      default_db: document.getElementById('c-db').value.trim() || null,
      protected: document.getElementById('c-prot').checked,
    };
  }

  function fillForm(c) {
    document.getElementById('c-alias').value = c ? c.alias : '';
    document.getElementById('c-host').value = c ? c.host : '';
    document.getElementById('c-port').value = c ? c.port : 3306;
    document.getElementById('c-user').value = c ? c.user : '';
    document.getElementById('c-pass').value = '';
    document.getElementById('c-db').value = c && c.default_db ? c.default_db : '';
    document.getElementById('c-prot').checked = c ? c.protected : false;
    document.getElementById('conn-form-title').textContent =
      c ? ('编辑连接：' + c.alias) : '新增连接';
  }

  async function refresh() {
    invalidateConnections();
    const list = await loadConnections();
    const tbody = document.querySelector('#conn-table tbody');
    tbody.innerHTML = '';
    list.forEach(c => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${c.alias}</td><td>${c.host}</td><td>${c.port}</td>
        <td>${c.user}</td><td>${c.default_db || '-'}</td>
        <td>${c.protected ? '✅' : ''}</td>
        <td><button class="btn gray" data-edit="${c.alias}">编辑</button>
            <button class="btn red" data-del="${c.alias}">删除</button></td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
      fillForm(list.find(c => c.alias === b.dataset.edit)));
    tbody.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      if (!await showConfirm(`删除连接 <b>${b.dataset.del}</b>？`)) return;
      await api('DELETE', '/api/connections/' + encodeURIComponent(b.dataset.del));
      toast('已删除');
      refresh();
    });
  }

  document.getElementById('c-save').onclick = async () => {
    const body = formBody();
    if (!body.alias || !body.host || !body.user) { toast('别名/主机/用户必填', true); return; }
    await api('POST', '/api/connections', body);
    toast('已保存');
    fillForm(null);
    refresh();
  };
  document.getElementById('c-test').onclick = async () => {
    const out = await api('POST', '/api/connections/test', formBody());
    toast(out.ok ? '连接成功' : '连接失败', !out.ok);
  };
  document.getElementById('c-reset').onclick = () => fillForm(null);

  refresh();
})();
