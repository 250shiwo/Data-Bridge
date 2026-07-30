// 外壳入口：左栏拖拽调宽 + 模块初始化（脚本最后加载）
(function () {
  const sidebar = document.getElementById('sidebar');
  document.getElementById('splitter').onmousedown = e => {
    e.preventDefault();
    const startX = e.clientX, startW = sidebar.offsetWidth;
    const move = ev => {
      sidebar.style.width = Math.min(520, Math.max(160, startW + ev.clientX - startX)) + 'px';
    };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  };
  document.getElementById('btn-new-conn').onclick = () => ConnDialog.openNew();
  Tree.init(sidebar);
})();
