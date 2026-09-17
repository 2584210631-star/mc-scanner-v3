# -*- coding: utf-8 -*-
"""运行时注入 UI 增强样式、移动端底栏、人格卡片选择。"""
import os
from flask import Response, send_from_directory

_PERSONA_JS = r"""
<script>
(function(){
  function upgradePersonaUI(personas) {
    const sel = document.getElementById('aiBotPersonaSelect');
    if (sel && personas && personas.length) {
      const cur = sel.value;
      sel.innerHTML = '<option value="">选择预设人格...</option>' +
        personas.map(function(p,i){return '<option value="'+i+'">'+(p.label||p.name)+'</option>';}).join('');
      if (cur) sel.value = cur;
    }
    var host = document.getElementById('personaCardGrid');
    if (!host) {
      var multiCount = document.getElementById('multiCount');
      if (!multiCount) return;
      host = document.createElement('div');
      host.id = 'personaCardGrid';
      host.className = 'persona-grid';
      var row = multiCount.closest('.form-row') || multiCount.parentElement;
      if (row && row.parentElement) row.parentElement.insertBefore(host, row.nextSibling);
      else return;
      var tip = document.createElement('p');
      tip.className = 'hint';
      tip.textContent = '点选参与互聊的人格（可多选，不选则随机）';
      host.parentElement.insertBefore(tip, host);
    }
    if (!personas || !personas.length) return;
    host.innerHTML = personas.map(function(p,i){
      var label = p.label || p.name || ('人格'+(i+1));
      var prev = (p.preview || p.persona || '').slice(0, 42);
      return '<label class="persona-card" data-idx="'+i+'">' +
        '<input type="checkbox" class="persona-cb" value="'+i+'">' +
        '<div class="pc-label">'+label+'</div>' +
        '<div class="pc-name">'+(p.name||'')+'</div>' +
        '<div class="pc-preview">'+prev+'</div></label>';
    }).join('');
    host.querySelectorAll('.persona-card').forEach(function(card){
      card.addEventListener('click', function(e){
        if (e.target.tagName === 'INPUT') return;
        var cb = card.querySelector('input');
        cb.checked = !cb.checked;
        card.classList.toggle('active', cb.checked);
      });
      var cb = card.querySelector('input');
      cb.addEventListener('change', function(){ card.classList.toggle('active', cb.checked); });
    });
  }
  function fetchPersonas() {
    fetch('/api/ai_multi/personas').then(function(r){return r.json();}).then(function(d){
      if (d && d.personas) upgradePersonaUI(d.personas);
    }).catch(function(){});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fetchPersonas);
  else fetchPersonas();
  document.querySelectorAll('.tab[data-tab="aibot"]').forEach(function(t){
    t.addEventListener('click', function(){ setTimeout(fetchPersonas, 50); });
  });
})();
</script>
"""

_NAV = r"""
<nav class="m-bottom-nav" id="mobileBottomNav" aria-label="主导航">
  <button type="button" data-tab="scan" onclick="switchTab('scan')"><span>◈</span>扫描</button>
  <button type="button" data-tab="results" onclick="switchTab('results')"><span>☰</span>结果</button>
  <button type="button" data-tab="observer" onclick="switchTab('observer')"><span>◎</span>观察</button>
  <button type="button" data-tab="aibot" onclick="switchTab('aibot')"><span>✦</span>AI</button>
  <button type="button" data-tab="settings" onclick="switchTab('settings')"><span>⚙</span>设置</button>
</nav>
<script>
(function(){
  const syncMobNav = (name) => {
    document.querySelectorAll('#mobileBottomNav button').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-tab') === name);
    });
  };
  const wrap = () => {
    const _orig = window.switchTab;
    if (typeof _orig !== 'function' || _orig._mobWrapped) return;
    window.switchTab = function(name) {
      const r = _orig.apply(this, arguments);
      try { syncMobNav(name); } catch (e) {}
      return r;
    };
    window.switchTab._mobWrapped = true;
  };
  setTimeout(wrap, 0);
  setTimeout(wrap, 400);
})();
</script>
"""


def serve_index(web_dir: str):
    html_path = os.path.join(web_dir, "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return send_from_directory(web_dir, "index.html")

    polish_path = os.path.join(web_dir, "ui-polish.css")
    if os.path.isfile(polish_path) and "UI polish v3.4.1" not in html and "persona-grid" not in html:
        try:
            with open(polish_path, "r", encoding="utf-8") as f:
                polish_css = f.read()
            if "</style>" in html:
                html = html.replace("</style>", polish_css + "\n</style>", 1)
        except OSError:
            pass

    if 'id="mobileBottomNav"' not in html:
        if "</body>" in html:
            html = html.replace("</body>", _NAV + "</body>", 1)
        elif "</html>" in html:
            html = html.replace("</html>", _NAV + "</html>", 1)

    if "personaCardGrid" not in html:
        if "</html>" in html:
            html = html.replace("</html>", _PERSONA_JS + "\n</html>", 1)

    return Response(html, mimetype="text/html; charset=utf-8")
