# -*- coding: utf-8 -*-
"""运行时注入 UI 增强样式与移动端底栏，避免改动巨大的 index.html。"""
import os
from flask import Response, send_from_directory


def serve_index(web_dir: str):
    html_path = os.path.join(web_dir, "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return send_from_directory(web_dir, "index.html")

    polish_path = os.path.join(web_dir, "ui-polish.css")
    if os.path.isfile(polish_path) and "UI polish v3.4.1" not in html:
        try:
            with open(polish_path, "r", encoding="utf-8") as f:
                polish_css = f.read()
            if "</style>" in html:
                html = html.replace("</style>", polish_css + "\n</style>", 1)
        except OSError:
            pass

    if 'id="mobileBottomNav"' not in html:
        nav = """
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
        if "</body>" in html:
            html = html.replace("</body>", nav + "</body>", 1)
        elif "</html>" in html:
            html = html.replace("</html>", nav + "</html>", 1)

    return Response(html, mimetype="text/html; charset=utf-8")
