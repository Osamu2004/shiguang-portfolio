const CACHE='shiguang-v45';
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/','/style.css','/dashboard.css?v=20261008-2','/checkup.css','/accounts.css','/modules.css','/market.css','/holding-calendar.css?v=20261008-2','/allocation-plan.css?v=20261008-2','/app.js?v=20261008-3','/allocation-plan.js?v=20261008-2','/holding-calendar.js']))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('shiguang-')&&key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&!e.request.url.includes('/api/'))e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))});
