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
