// 公共工具：API 请求、toast、确认框、连接列表缓存

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* 非 JSON 响应 */ }
  if (!res.ok) {
    const msg = data.message || ('请求失败 HTTP ' + res.status);
    toast(msg, true);
    throw new Error(msg);
  }
  return data;
}

function toast(msg, isError) {
  const el = document.createElement('div');
  el.className = 'toast-item' + (isError ? ' err' : '');
  el.textContent = msg;
  document.getElementById('toast').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// 确认框：requireProtected 时必须勾选确认复选框才能点「确认执行」
function showConfirm(summaryHtml, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    const mask = document.getElementById('modal-mask');
    const modal = document.getElementById('modal');
    modal.innerHTML = `
      <h3>确认操作</h3>
      <div>${summaryHtml}</div>
      ${opts.requireProtected ? `
        <p style="color:#dc2626"><label>
          <input type="checkbox" id="m-protect"> 目标为受保护连接，我确认写入受保护库
        </label></p>` : ''}
      <div style="margin-top:12px;text-align:right">
        <button class="btn gray" id="m-cancel">取消</button>
        <button class="btn" id="m-ok">确认执行</button>
      </div>`;
    mask.style.display = 'block';
    const close = val => { mask.style.display = 'none'; resolve(val); };
    modal.querySelector('#m-cancel').onclick = () => close(false);
    modal.querySelector('#m-ok').onclick = () => {
      if (opts.requireProtected && !modal.querySelector('#m-protect').checked) {
        toast('请先勾选受保护库写入确认', true);
        return;
      }
      close(true);
    };
  });
}

// 连接列表缓存（含 protected 标记），保存/删除连接后需 invalidateConnections()
let _connCache = null;
async function loadConnections() {
  if (!_connCache) _connCache = await api('GET', '/api/connections');
  return _connCache;
}
function invalidateConnections() { _connCache = null; }
