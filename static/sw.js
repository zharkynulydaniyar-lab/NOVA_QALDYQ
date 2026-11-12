importScripts('/offline-store.js?v=4.2');
const CACHE='qaldyq-shell-v6.6-telegram';
const SHELL=['/','/index.html','/i18n.js?v=6.0','/i18n.css?v=5.4.0','/app.js?v=6.6-telegram','/features.js?v=6.6-telegram','/i18n-labour.js?v=6.0','/ops-labour.css?v=6.0','/ops-nav.css?v=6.0','/ops.js?v=6.0','/ops-canteen.js?v=6.0','/ops-kitchen.js?v=6.0','/ops-actions.js?v=6.0','/ops-forecast.js?v=6.0','/i18n-ops.js?v=6.0','/ops.css?v=6.0','/features.css?v=5.4.0','/offline-store.js?v=4.2','/vendor/qrcode.js','/styles.css','/studio.css?v=2','/animations.css?v=3','/animations.js?v=6.0','/vendor/three.module.js','/vendor/three.core.js','/student/','/student/student.js?v=6.6-telegram','/student/student.css?v=6.0','/student/manifest.webmanifest','/student/icon-192.png','/favicon.svg','/campus-3d-v2.png','/cycle-3d-v2.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('qaldyq-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(url.origin!==location.origin||event.request.method!=='GET'||url.pathname.startsWith('/api/'))return;
  if(event.request.mode==='navigate'){
    event.respondWith(fetch(event.request).catch(()=>caches.match(url.pathname.startsWith('/student')?'/student/':'/')));return;
  }
  if(SHELL.includes(url.pathname+url.search)||SHELL.includes(url.pathname))event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request)));
});
self.addEventListener('sync',event=>{if(event.tag==='qaldyq-reports')event.waitUntil(QStore.sync().then(async result=>{for(const client of await self.clients.matchAll())client.postMessage({type:'synced',...result});}));});
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(self.clients.matchAll({type:'window'}).then(async clients=>{if(clients[0]){await clients[0].focus();clients[0].postMessage({type:'notifications'});}else await self.clients.openWindow('/#notifications');}));});
