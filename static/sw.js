const CACHE='shiguang-v43';
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/','/style.css','/dashboard.css','/checkup.css','/accounts.css','/modules.css','/market.css','/holding-calendar.css','/allocation-plan.css?v=20261008-1','/app.js?v=20261008-1','/allocation-plan.js?v=20261008-1','/holding-calendar.js']))));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('shiguang-')&&key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&!e.request.url.includes('/api/'))e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))});
