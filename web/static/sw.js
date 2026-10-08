// MC Scanner PWA Service Worker
// 发版时更新版本号，activate 阶段会清理旧缓存
const CACHE_NAME = 'mcscanner-v3-v3.7.0';
const STATIC_ASSETS = ['/static/icon-192.png', '/static/icon-512.png'];

// 只缓存同源静态资源：页面、接口、带查询串的响应（如 /auth-response?code=…）一律不落盘
const CACHEABLE = /^\/static\/[^?]*\.(?:png|jpe?g|svg|ico|css|js|woff2?)$/;

self.addEventListener('install', e => {
  // 逐个缓存并吞掉单个资源的失败：原先的 addAll 只要有一个 404，整个 install 就失败、SW 永不安装
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(c => Promise.all(STATIC_ASSETS.map(u => c.add(u).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // 跨域 CDN 脚本交给浏览器默认策略（不缓存：无 SRI 时缓存会把被污染的脚本长期固定）
  if (url.origin !== self.location.origin) return;
  // 接口、SW 自身、任何带查询串的请求（OAuth 授权码等）都不缓存
  if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return;
  if (url.search) return;
  // 页面导航走网络：cache-first 会让用户长期拿到旧页面，也避免把页面（含注入内容）写进磁盘缓存
  if (req.mode === 'navigate' || url.pathname === '/') return;

  if (!CACHEABLE.test(url.pathname)) return;

  // 静态资源：stale-while-revalidate
  e.respondWith(
    caches.match(req).then(cached => {
      const network = fetch(req).then(res => {
        if (res && res.ok) {
          const clone = res.clone();
          // 必须用 event.waitUntil 包裹，否则浏览器可能在 put 完成前终止 SW
          e.waitUntil(caches.open(CACHE_NAME).then(c => c.put(req, clone)).catch(() => {}));
        }
        return res;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
