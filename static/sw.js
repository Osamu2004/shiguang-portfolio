const CACHE='shiguang-v46';
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/','/style.css?v=20261008-4','/dashboard.css?v=20261008-2','/checkup.css','/accounts.css','/modules.css','/market.css','/holding-calendar.css?v=20261008-2','/allocation-plan.css?v=20261008-2','/privacy.css?v=20261008-4','/app.js?v=20261008-4','/allocation-plan.js?v=20261008-4','/holding-calendar.js?v=20261008-4']))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('shiguang-')&&key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&!e.request.url.includes('/api/'))e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))});
