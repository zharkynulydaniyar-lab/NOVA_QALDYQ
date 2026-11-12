'use strict';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (n, digits = 0) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(Number(n) || 0);
const money = n => `${fmt(n)} ₸`;
const monthsKk = ['қаң.','ақп.','нау.','сәу.','мам.','мау.','шіл.','там.','қыр.','қаз.','қар.','жел.'];
const dates = d => `${Number(d.slice(8,10))} ${monthsKk[Number(d.slice(5,7))-1]}`;
const localTime = stamp => { const parts = new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Qyzylorda',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(stamp)); return parts; };
const roleNames = { operator:'Жауапты қызметкер', reviewer:'Тексеруші', manager:'Басшылық', admin:'Әкімші' };
const statusNames = { draft:'Черновик', submitted:'Жіберілді', in_review:'Тексерілуде', accepted:'Қабылданды', returned:'Қайтарылды' };
const routeNames = { tbo:'ТҚҚ шығару', tbo_bin:'ТҚҚ шығару (қоқыс жәшігі)', recycling:'Қайта өңдеу', compost:'Компосттау', disposal:'Жоюға жіберу' };
const unitNames = { kg:'кг', l:'л' };
// crypto.randomUUID exists only on HTTPS/localhost; a phone on the campus LAN opens plain HTTP.
const uuid = () => globalThis.crypto?.randomUUID ? crypto.randomUUID() : [...crypto.getRandomValues(new Uint8Array(16))].map((b,i)=>([4,6,8,10].includes(i)?'-':'')+b.toString(16).padStart(2,'0')).join('');
const palette = ['#075c46','#85b567','#c6d49a','#dca664','#a0bfc2','#bda5cd'];
const paths = {
  grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  file:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5',
  building:'M3 21h18M5 21V7l7-4 7 4v14M9 10h1m4 0h1m-6 4h1m4 0h1m-5 7v-4h4v4',
  leaf:'M20 3C9 2 3 7 4 14c1 7 10 8 14 2 3-4 2-10 2-13ZM5 20 16 9',
  chart:'M4 3v17h17M8 15l4-6 4 3 5-7',
  arrow:'M7 17 17 7M7 7h10v10',
  down:'m6 9 6 6 6-6',
  plus:'M12 5v14M5 12h14',
  search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  bell:'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4',
  download:'M12 3v12m-5-5 5 5 5-5M5 16v5h14v-5',
  clock:'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  check:'m5 12 4 4L19 6',
  chevron:'m9 5 7 7-7 7',
  close:'m6 6 12 12M6 18 18 6',
  logout:'M9 5H4v14h5M10 12h11m-4-4 4 4-4 4',
  info:'M12 11v6M12 7h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  scale:'M12 3v18M4 7h16M7 7l-4 8h8L7 7Zm10 0-4 8h8l-4-8ZM7 21h10',
  coins:'M20 7c0 2-4 4-8 4S4 9 4 7s4-4 8-4 8 2 8 4ZM4 7v5c0 2 4 4 8 4s8-2 8-4V7M4 12v5c0 2 4 4 8 4s8-2 8-4v-5',
  recycle:'m8 5 3-3 3 3M11 2v7M18 8l4 1-1 4M22 9l-6 4M15 20l-1 3-4-1M14 23l-3-7M5 15l-4-1 1-4M1 14l6-3',
  menu:'M4 6h16M4 12h16M4 18h16',
  book:'M12 5c-4-3-8-2-10-1v15c3-1 6-2 10 1m0-15c4-3 8-2 10-1v15c-3-1-6-2-10 1V5',
  camera:'M4 6h4l2-3h4l2 3h4v14H4ZM16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
};
const icon = (name, cls='') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
function periodRange(period,today,demoDay){
  const end=period==='demo'?demoDay:today,start=new Date(end+'T12:00:00Z');
  if(period==='week')start.setUTCDate(start.getUTCDate()-6);
  else if(period==='year')start.setUTCMonth(0,1);
  else if(period==='quarter')start.setUTCMonth(Math.floor(start.getUTCMonth()/3)*3,1);
  else start.setUTCDate(1);
  return {start:start.toISOString().slice(0,10),end};
}
const state = { view:'dashboard', boot:null, reports:[], previous:[], start:'', end:'', org:'0', category:'0', status:'all', search:'', page:1, period:'quarter', loading:false, labour:{records:300,paper:3,system:0.5,merge:480,mergeSystem:20,rate:1500}, impact:{kg:1000,cost:1200,reduction:15,capex:350000,opex:30000,co2:2.5} };
let csrf = '', toastTimer, loadSequence = 0;

async function api(path, options={}) {
  let response;
  try {response=await fetch(path, { credentials:'same-origin', ...options, headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,...options.headers}, body:options.body ? JSON.stringify(options.body) : undefined });}
  catch {state.connected=false;const error=new Error('Сервермен байланыс жоқ. Есепті құрылғыға сақтауға болады.');error.network=true;throw error;}
  state.connected=true;
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && state.boot) { state.boot = null; renderLogin(); }
    const error=new Error(data.error || 'Сұрау орындалмады.');error.status=response.status;throw error;
  }
  return data;
}
function toast(message, error=false) {
  const el = $('#toast'); el.textContent = message; el.className = `toast show ${error ? 'error' : ''}`;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 5000);
}
function badge(status) { return `<span class="badge ${esc(status)}"><i></i>${esc(statusNames[status])}</span>`; }
function queryString() { return new URLSearchParams({start:state.start,end:state.end,org:state.org,category:state.category}).toString(); }
const routeList = () => state.boot?.routes?.length ? state.boot.routes : Object.entries(routeNames).map(([code,name])=>({code,name}));
const routeName = code => routeList().find(r=>r.code===code)?.name || routeNames[code] || code;
// Each organization has its own waste list (ТЗ, ФТ-1.1); "all organizations" shows the whole directory.
const orgCategories = org => { const all=state.boot.categories, ids=state.boot.org_categories?.[String(org)]; return !Number(org)||!ids ? all : all.filter(c=>ids.includes(c.id)); };
const canCreate = () => ['operator','admin'].includes(state.boot.user.role);
const canReview = () => state.boot.user.role==='reviewer' || (state.boot.user.role==='admin' && state.boot.user.can_review!==0);
const extraViews = () => Object.entries(window.QaldyqViews||{}).filter(([,v])=>v.roles.includes(state.boot.user.role));
const orgName = id => state.boot.organizations.find(o => o.id === Number(id))?.name || '';
const accepted = () => state.reports.filter(r => r.status === 'accepted');
const sum = (rows, key) => rows.reduce((s,r) => s + Number(r[key] || 0), 0);

function renderLogin() {
  $('#app').innerHTML = `<main class="login-layout" id="main"><section class="login-story" data-parallax><div class="brand"><img src="/favicon.svg" alt=""><span>qaldyq<span class="brand-dot">.</span></span></div><div class="story-copy"><span class="eyebrow light">SMART FOOD INDUSTRIES · ATU</span><h1>Әр килограмм<br>есепте.</h1><p>Кампус қалдықтарын тіркеңіз.<br>Деректі шешімге, қалдықты ресурсқа айналдырыңыз.</p><div class="login-campus"><img src="/campus-3d-v2.png" width="1254" height="1254" alt="Жасыл кампустың 3D иллюстрациясы" decoding="async"></div></div><div class="story-footer"><span>01 / Цифрлық кампус</span><span>ATU · 2026</span></div></section><section class="login-panel"><div class="login-box"><div class="login-language">${QaldyqI18n.switcher()}</div><span class="pill">${icon('leaf')} Кампус ресурстары платформасы</span><h2>Қош келдіңіз</h2><p class="muted">Жұмыс кеңістігіне кіру үшін рөліңізді таңдаңыз.</p><div class="demo-note">Демо нұсқа · Барлық деректер ойдан құрастырылған.</div><form id="login-form"><label for="login-role">Демо аккаунт</label><select id="login-role"><option value="manager@atu.kz">Басшылық — жалпы көрініс</option><option value="operator@atu.kz">Қызметкер — есеп енгізу</option><option value="reviewer@atu.kz">Тексеруші — есепті қабылдау</option><option value="admin@atu.kz">Әкімші — анықтамалықтар</option></select><label for="login-email">Email</label><input id="login-email" type="email" value="manager@atu.kz" required autocomplete="username"><label for="login-password">Құпиясөз</label><input id="login-password" type="password" value="demo2026" required autocomplete="current-password"><p class="small muted">Демо аккаунттардың құпиясөзі: <strong>demo2026</strong></p><p id="login-error" class="form-error" role="alert"></p><button class="btn primary full" type="submit">Жұмыс кеңістігіне кіру ${icon('arrow')}</button></form><p class="small"><a class="text-link" href="/student/">Студент қосымшасы: мәзір және алдын ала тапсырыс ${icon('arrow')}</a></p><div class="login-foot">Жауапты есеп. Тексерілген дерек. Өлшенетін әсер.</div></div></section></main>`;
  bindStudio();
  $('#login-role').addEventListener('change', e => { $('#login-email').value = e.target.value; });
  // Every demo account (all organizations and roles) can be picked here; the list is served only in demo mode.
  fetch('/api/public/demo-accounts').then(r=>r.json()).then(data=>{const select=$('#login-role');if(!select||!data.accounts?.length)return;const labels={operator:'Қызметкер',reviewer:'Тексеруші',manager:'Басшылық',admin:'Әкімші',student:'Студент'};select.innerHTML=data.accounts.map(a=>`<option value="${esc(a.email)}" ${a.email==='manager@atu.kz'?'selected':''}>${labels[a.role]}${a.org_name?' — '+esc(a.org_name):''}</option>`).join('');QaldyqI18n.apply(select);}).catch(()=>{});
  $('#login-form').addEventListener('submit', async e => {
    e.preventDefault(); const button = $('button[type=submit]',e.target); button.disabled = true; $('#login-error').textContent = '';
    try { const result=await api('/api/login', {method:'POST',body:{email:$('#login-email').value,password:$('#login-password').value}}); if(result.role==='student'){location.href='/student/';return;} await boot(); }
    catch(error) { $('#login-error').textContent = error.message; } finally { button.disabled = false; }
  });
  QaldyqI18n.apply();
}

async function boot() {
  try {
    const previousUser=state.boot?.user.id;
    try {state.boot = await api('/api/bootstrap');}
    catch(error){if(!error.network)throw error;const active=await QStore.get('active-user');const cached=await QStore.get('boot');if(!cached||cached.user.id!==active)throw error;state.boot=cached;}
    csrf = state.boot.csrf;
    if(previousUser!==state.boot.user.id){state.reports=[];state.previous=[];state.food=null;state.inbox=null;state.period='quarter';state.category='0';Object.assign(state,periodRange('quarter',state.boot.today,state.boot.demo_date));}
    if (state.boot.user.role === 'operator') state.org = String(state.boot.user.org_id); else state.org = '0';
    state.view = location.hash === '#new-report' ? 'reports' : location.hash==='#notifications'?'notifications':'dashboard';
    renderShell(); await loadData();
    await featuresBoot();
    if(location.hash==='#report'){
      const reportId=Number(new URLSearchParams(location.search).get('report'));
      if(Number.isSafeInteger(reportId)&&reportId>0)await openReport(reportId);
    }
    if (location.hash === '#new-report' && canCreate()) {
      const org=Number(new URLSearchParams(location.search).get('org'));
      if(org&&state.boot.user.role==='operator'&&org!==state.boot.user.org_id)toast('Бұл QR басқа ұйымға арналған. Өз асханаңыздың QR-кодын қолданыңыз.',true);
      else if(org&&!state.boot.organizations.some(o=>o.id===org))toast('QR-кодтағы ұйым табылмады.',true);
      else openReportForm(org?{org_id:org,_local:true}:null);
      history.replaceState(null,'',location.pathname+location.search);
    }
  } catch(error) {
    if (error.message !== 'Жүйеге кіріңіз.') toast(error.message, true);
    renderLogin();
  }
}

function renderShell() {
  const {user} = state.boot;
  const nav = [['dashboard','grid','Жалпы көрініс'],['reports','file','Қалдық есебі'],['food','leaf','Ас мәзірі және жоспар'],['qr','grid','Асхана QR-кодтары'],['notifications','bell','Хабарламалар'],['organizations','building','Ұйымдар'],['impact','chart','Әсер калькуляторы'],['guide','book','Жоба паспорты']];
  const base=nav.splice(2), extras=extraViews().map(([key,v])=>[key,v.icon,v.label]); nav.push(...extras.slice(0,2),...base,...extras.slice(2));
  $('#app').innerHTML = `<div class="app-shell"><aside class="sidebar" id="sidebar"><a class="brand" href="#" data-view="dashboard"><img src="/favicon.svg" alt=""><span>qaldyq<span class="brand-dot">.</span></span></a><div class="workspace"><span class="workspace-logo">A</span><div><strong>ATU Campus</strong><span>Алматы технологиялық университеті</span></div></div><div class="nav-caption">ЖҰМЫС КЕҢІСТІГІ</div><nav aria-label="Негізгі мәзір">${nav.map(([key,ico,label]) => `<button data-view="${key}" class="nav-item ${state.view===key?'active':''}">${icon(ico)}<span>${label}</span>${key==='reports'?'<span class="nav-count" id="pending-count">0</span>':''}</button>`).join('')}</nav><div class="sidebar-bottom"><div class="campus-card"><span class="tiny-label">БІРГЕ ӨЗГЕРТЕМІЗ</span>${icon('leaf')}<strong>Қалдық аз.<br>Мүмкіндік көп.</strong><span>ЦУР 12 · Жауапты тұтыну</span></div><div class="profile"><span class="avatar">${esc(user.name.split(' ').map(n=>n[0]).slice(0,2).join(''))}</span><div><strong>${esc(user.name)}</strong><span>${roleNames[user.role]}</span></div><button class="icon-btn" id="logout" aria-label="Шығу және рөлді ауыстыру" title="Рөлді ауыстыру">${icon('logout')}</button></div></div></aside><div class="content-wrap"><header class="topbar"><div class="breadcrumb"><button class="icon-btn mobile-menu" id="mobile-menu" aria-label="Мәзірді ашу">${icon('menu')}</button><span>Жұмыс кеңістігі</span>${icon('chevron')}<strong id="crumb">Жалпы көрініс</strong></div><div class="top-actions">${QaldyqI18n.switcher()}${canCreate()?`<button class="btn primary small" id="quick-entry">${icon('plus')} Жылдам енгізу</button>`:''}<span class="demo-chip"><i></i> Демо деректер</span><button class="icon-btn" id="notifications" aria-label="Ескерту мен мерзімдер">${icon('bell')}<span class="notification-dot"></span></button><button class="top-avatar" id="switch-account" aria-label="Аккаунтты ауыстыру" title="Аккаунтты ауыстыру">${esc(user.name[0])}</button></div></header><main id="main" class="main" tabindex="-1"></main><footer class="app-footer"><span>Qaldyq · ATU Smart Food Industries</span><span>Демо кезең: 2026 жылғы қыркүйек–қазан</span></footer></div></div>`;
  $$('[data-view]').forEach(el => el.addEventListener('click', e => {e.preventDefault(); navigate(el.dataset.view);}));
  $('#logout').addEventListener('click', async () => { try {await api('/api/logout',{method:'POST',body:{}});await QStore.del('boot');await QStore.del('active-user');state.boot=null;csrf='';renderLogin();} catch(error){toast(error.message,true);} });
  $('#mobile-menu').addEventListener('click', () => $('#sidebar').classList.toggle('mobile-open'));
  $('#notifications').addEventListener('click', () => navigate('notifications'));
  $('#switch-account').addEventListener('click', () => openSwitch());
  if($('#quick-entry'))$('#quick-entry').addEventListener('click', () => openQuick());
  QaldyqI18n.apply();
}

function navigate(view) {
  state.view = view; state.page = 1; state.search=''; state.status='all';
  $$('.nav-item').forEach(b => b.classList.toggle('active',b.dataset.view===view));
  $('#sidebar').classList.remove('mobile-open'); renderMain(); window.scrollTo(0,0);
  if(view==='food')loadFood();
  if(view==='notifications')pollNotifications();
  window.QaldyqViews?.[view]?.load?.();
}

async function loadData() {
  const sequence = ++loadSequence;
  const userId=state.boot.user.id,query=queryString();
  state.loadError='';
  state.loading = true; renderMain();
  const end = new Date(state.start+'T12:00:00'); end.setDate(end.getDate()-1);
  const days = Math.round((new Date(state.end+'T12:00:00') - new Date(state.start+'T12:00:00'))/86400000)+1;
  let start = new Date(end); start.setDate(start.getDate()-days+1);
  // Month, quarter and year presets compare with the same span of the previous calendar period.
  const shift = {month:1,quarter:3,year:12}[state.period];
  if(shift){const back=value=>{const d=new Date(value+'T12:00:00'),day=d.getDate();d.setDate(1);d.setMonth(d.getMonth()-shift);d.setDate(Math.min(day,new Date(d.getFullYear(),d.getMonth()+1,0).getDate()));return d;};start=back(state.start);end.setTime(back(state.end).getTime());}
  const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  try {
    const [current, previous] = await Promise.all([api('/api/reports?'+query), api('/api/reports?'+new URLSearchParams({start:iso(start),end:iso(end),org:state.org}))]);
    if (sequence !== loadSequence||state.boot?.user.id!==userId) return;
    state.reports=current.reports; state.previous=previous.reports;
    await QStore.set('reports:'+userId+':'+query,{current,previous});
    if(sequence!==loadSequence||state.boot?.user.id!==userId)return;
    $('#pending-count').textContent = state.reports.filter(r => ['submitted','in_review'].includes(r.status)).length;
  } catch(error) {const cached=error.network&&await QStore.get('reports:'+userId+':'+query);if(sequence!==loadSequence||state.boot?.user.id!==userId)return;if(cached){state.reports=cached.current.reports;state.previous=cached.previous.reports;}else{state.reports=[];state.previous=[];state.loadError=error.message;toast(error.message,true);}}
  finally { if(sequence===loadSequence && state.boot?.user.id===userId) {state.loading=false;$('#pending-count').textContent=state.reports.filter(r=>['submitted','in_review'].includes(r.status)).length;renderMain();} }
  if(state.boot?.user.id===userId&&state.view==='food')await loadFood();
  const extra=window.QaldyqViews?.[state.view];if(state.boot?.user.id===userId&&extra?.reload)await extra.load();
  if(state.boot?.user.id===userId&&state.view==='dashboard'&&typeof loadDashboardExtras==='function')loadDashboardExtras();
}

function filters() {
  const isOperator=state.boot.user.role==='operator';
  return `<div class="filter-row"><div class="period-tabs" role="group" aria-label="Кезең"><button data-period="week" class="${state.period==='week'?'selected':''}">7 күн</button><button data-period="month" class="${state.period==='month'?'selected':''}">Ай</button><button data-period="quarter" class="${state.period==='quarter'?'selected':''}">Тоқсан</button><button data-period="year" class="${state.period==='year'?'selected':''}">Жыл</button><button data-period="demo" class="${state.period==='demo'?'selected':''}">Демо кезең</button></div><div class="filter-inputs"><label class="sr-only" for="filter-start">Кезең басы</label><input type="date" id="filter-start" value="${state.start}" max="${state.end}" aria-label="Кезең басы"><span class="muted">—</span><label class="sr-only" for="filter-end">Кезең соңы</label><input type="date" id="filter-end" value="${state.end}" min="${state.start}" aria-label="Кезең соңы"><label class="sr-only" for="filter-org">Ұйым</label><select id="filter-org" ${isOperator?'disabled':''}><option value="0">Барлық ұйымдар</option>${state.boot.organizations.map(o=>`<option value="${o.id}" ${String(o.id)===state.org?'selected':''}>${esc(o.name)}</option>`).join('')}</select><label class="sr-only" for="filter-category">Қалдық түрі</label><select id="filter-category"><option value="0">Барлық қалдық түрі</option>${orgCategories(state.org).map(c=>`<option value="${c.id}" ${String(c.id)===state.category?'selected':''}>${esc(c.name)}</option>`).join('')}</select></div></div>`;
}
function heading(title, subtitle, actions='') { return `<div class="page-heading"><div><div class="eyebrow">КАМПУС РЕСУРСТАРЫ</div><h1>${title}</h1><p>${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`; }
function createButton() { return canCreate()?`<button class="btn primary" data-action="create">${icon('plus')} Жаңа есеп</button>`:`<button class="btn primary" data-view-action="reports">${icon('file')} ${canReview()?'Есептерді тексеру':'Есептерді көру'}</button>`; }

function renderMain() {
  if (!state.boot) return;
  const names={dashboard:'Жалпы көрініс',reports:'Қалдық есебі',food:'Ас мәзірі және жоспар',qr:'Асхана QR-кодтары',notifications:'Хабарламалар',organizations:'Ұйымдар',impact:'Әсер калькуляторы',guide:'Жоба паспорты'};
  for(const [key,view] of extraViews())names[key]=view.label;
  if(!names[state.view])state.view='dashboard';
  $('#crumb').textContent=names[state.view];
  if(state.loadError&&['dashboard','reports','food','organizations'].includes(state.view)){
    $('#main').innerHTML=heading(names[state.view],'')+filters()+`<section class="panel food-panel" role="alert"><h2>Кезең дерегін жүктеу мүмкін болмады.</h2><p>${esc(state.loadError)}</p><button class="btn primary" id="reload-data">Қайта жүктеу</button></section>`;
    $('#main').setAttribute('aria-busy','false');bindCommon();$('#reload-data').onclick=loadData;QaldyqI18n.apply();return;
  }
  const views={dashboard:dashboardView,reports:reportsView,food:foodView,qr:qrView,notifications:notificationsView,organizations:organizationsView,impact:impactView,guide:guideView};
  for(const [key,view] of extraViews())views[key]=view.render;
  const retainedScenes = new Map($$('[data-worker-scene]').map(el=>[el.dataset.workerScene,el]));
  $('#main').innerHTML = state.loading && !state.reports.length ? '<div class="loading">Деректер жүктелуде…</div>' : views[state.view]();
  $$('[data-worker-scene]').forEach(el=>{const retained=retainedScenes.get(el.dataset.workerScene);if(retained)el.replaceWith(retained);});
  $('#main').setAttribute('aria-busy',String(state.loading));
  bindCommon();
  if(state.view==='impact') bindImpact();
  if(state.view==='food')bindFood();
  if(state.view==='qr')bindQr();
  if(state.view==='notifications')bindNotifications();
  if(!(state.loading&&!state.reports.length))window.QaldyqViews?.[state.view]?.bind?.();
  QaldyqI18n.apply();
}

function statsCards() {
  const rows=accepted(), previous=state.previous.filter(r=>r.status==='accepted');
  const kg=sum(rows,'kg'), prior=sum(previous,'kg');
  const change=prior?Math.round((kg-prior)/prior*100):null;
  const diverted=kg?sum(rows,'diverted_kg')/kg*100:0,recyclable=kg?sum(rows,'recyclable_kg')/kg*100:0;
  return `<div class="stat-grid"><article class="stat-card"><div class="stat-label">Тіркелген қалдық ${icon('scale')}</div><div class="stat-value">${fmt(kg,1)} <span>кг</span></div><div class="stat-foot">${change!==null?`<span class="trend ${change<=0?'good':'bad'}">${change<=0?'↘':'↗'} ${Math.abs(change)}%</span><span>${{month:'алдыңғы аймен',quarter:'алдыңғы тоқсанмен',year:'алдыңғы жылмен'}[state.period]||'алдыңғы тең кезеңмен'}</span>`:'<span>Салыстыруға алдыңғы дерек жоқ</span>'}</div></article><article class="stat-card"><div class="stat-label">Қалдық құнының бағасы ${icon('coins')}</div><div class="stat-value">${fmt(sum(rows,'cost'))} <span>₸</span></div><div class="stat-foot">Масса × санаттың есептік құны</div></article><article class="stat-card"><div class="stat-label">Көміртек ізі · бағалау ${icon('leaf')}</div><div class="stat-value">${fmt(sum(rows,'co2')/1000,2)} <span>т CO₂e</span></div><div class="stat-foot">Демо коэффициенттер бойынша</div></article><article class="stat-card"><div class="stat-label">Өңдеуге бағытталған ${icon('recycle')}</div><div class="stat-value">${fmt(diverted,1)} <span>%</span></div><div class="mini-progress"><i style="width:${diverted}%"></i></div><div class="stat-foot">${fmt(sum(rows,'diverted_kg'),1)} кг · өңделгені расталмаған</div><div class="stat-foot">Түрі бойынша қайта өңдеуге жарамды: ${fmt(recyclable,1)}%</div></article></div>`;
}

function workerScene(kind){return `<div class="worker-scene" data-worker-scene="${kind}"><div class="scene-step"><span data-motion-step>Көрініс дайындалуда…</span></div></div>`;}
function studioHero(){
  const cards=[['clean','01','Қалдық жинау','Тазалау және бөлек жинау.','data-view-action="organizations"','Ұйымдарды көру'],['weigh','02','Таразыда өлшеу','Дәл өлшемнен сенімді есепке.','data-view-action="reports"','Қалдық есебін ашу'],['count','03','Санау және тіркеу','Әр затты сұрыптап, есепке алу.','data-view-action="impact"','Әсер калькуляторын ашу']];
  return `<section class="motion-section"><div class="motion-section-head"><div><span class="studio-kicker">КҮНДЕЛІКТІ ПРОЦЕСС</span><h2>Жинау. Өлшеу. Есепке алу.</h2><p>Кампус жұмысының анимациялық көріністері</p></div><button class="motion-control" data-motion-toggle aria-pressed="false" aria-label="Анимацияларды тоқтату">Ⅱ Тоқтату</button></div><div class="motion-grid">${cards.map(([kind,no,title,desc,action,label])=>`<article class="motion-card"><div class="motion-card-header"><span>${no}</span><h3>${title}</h3><i aria-hidden="true"></i></div>${workerScene(kind)}<div class="motion-card-footer"><p>${desc}</p><button class="round-link" ${action} aria-label="${label}">${icon('arrow')}</button></div></article>`).join('')}</div><p class="motion-demo-note">3D көріністер — процестің иллюстрациясы. Таразы мен санау мәндері демонстрациялық.</p></section>`;
}
function workerBanner(kind){
  const content={weigh:['ДӘЛ ӨЛШЕМ','Алдымен өлшеңіз. Содан кейін тіркеңіз.','Қалдық түрін, нақты массасын және бағытын көрсетіңіз. Сақталған есеп тексерушіге жіберіледі.'],count:['ЕСЕПКЕ АЛУ','Әр қалдықтың өз есебі бар.','Сұрыпталған заттарды санау және өлшенген массаны тіркеу ресурстардың қозғалысын түсінуге көмектеседі.']}[kind];
  return `<section class="motion-banner">${workerScene(kind)}<div class="motion-banner-copy"><span class="studio-kicker">${content[0]}</span><h2>${content[1]}</h2><p>${content[2]}</p><button class="motion-control" data-motion-toggle aria-pressed="false" aria-label="Анимацияларды тоқтату">Ⅱ Тоқтату</button><p class="motion-demo-note">Анимациядағы мәндер — демонстрациялық.</p></div></section>`;
}

function dashboardView() {
  const rows=accepted(), kg=sum(rows,'kg'), pending=state.reports.filter(r=>['submitted','in_review'].includes(r.status)).length;
  const organizations=state.boot.organizations.filter(o=>state.org==='0'||o.id===Number(state.org));
  const submittedOrgs=new Set(state.reports.filter(r=>r.status!=='draft'&&r.status!=='returned').map(r=>r.org_id));
  const missing=organizations.filter(o=>!submittedOrgs.has(o.id));
  return heading('Кампусқа шолу','Қалдық есебі, ресурстар және экологиялық көрсеткіштер.',createButton())+
    studioHero(rows)+
    filters()+statsCards()+(typeof dashboardExtras==='function'?dashboardExtras():'')+
    `<div class="chart-grid"><section class="panel chart-panel"><div class="panel-title"><div><h2>Қалдық динамикасы</h2><p>Қабылданған есептер · килограмм</p></div><span class="legend-dot">Ағымдағы кезең</span></div>${lineChart(rows)}</section><section class="panel"><div class="panel-title"><div><h2>Қалдық құрамы</h2><p>Түрлер бойынша бөлініс</p></div>${icon('leaf')}</div>${compositionChart(rows,kg)}</section></div>`+
    `<section class="panel chart-panel"><div class="panel-title"><div><h2>Ұйымдарды салыстыру</h2><p>Қабылданған есептер · килограмм</p></div>${icon('building')}</div>${orgChart(rows)}</section>`+
    `<div class="insight-row"><div class="insight"><span class="insight-icon amber">${icon('clock')}</span><div><strong>${pending} есеп тексеруді күтуде</strong><p>Қабылданған деректер ғана аналитикаға қосылады.</p></div><button class="text-link" data-action="pending">Қарау ${icon('chevron')}</button></div><div class="insight"><span class="insight-icon mint">${icon('building')}</span><div><strong>${submittedOrgs.size}/${organizations.length} ұйым есеп жіберді</strong><p>${missing.length ? esc(missing.map(o=>o.name).join(', '))+' · есеп күтілуде' : 'Таңдалған кезеңде барлық ұйым есеп жіберген.'}</p></div></div></div>`+
    `<section class="panel"><div class="panel-title"><div><h2>Соңғы есептер</h2><p>Ұйымдардан келіп түскен деректер</p></div><button class="text-link" data-view-action="reports">Барлық есептер ${icon('arrow')}</button></div>${reportTable(state.reports.slice(0,5))}</section>`+
    `<p class="data-note">${icon('info')} Демо деректер. Құн мен CO₂ — есептік бағалар. Қалдықтың өңдеуге жіберілуі оның нақты өңделгенін растамайды.</p>`;
}

function chartDataTable(data, title) {
  return `<details class="chart-data-table"><summary>${title}</summary><div class="table-scroll"><table><thead><tr><th>КЕЗЕҢ / САНАТ</th><th class="numeric">МАССА, КГ</th></tr></thead><tbody>${data.map(d=>`<tr><td>${esc(d.label)}</td><td class="numeric">${fmt(d.value,1)}</td></tr>`).join('')}</tbody></table></div></details>`;
}
function lineChart(rows) {
  const byDay={};rows.forEach(r=>byDay[r.report_date]=(byDay[r.report_date]||0)+r.kg);
  const start=new Date(state.start+'T12:00:00'),end=new Date(state.end+'T12:00:00');
  const days=Math.round((end-start)/86400000)+1,bucket=Math.max(1,Math.ceil(days/10)),values=[];
  for(let i=0;i<days;i+=bucket){let value=0,label='';for(let j=i;j<Math.min(i+bucket,days);j++){const d=new Date(start);d.setDate(d.getDate()+j);const key=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;if(!label)label=dates(key);value+=byDay[key]||0;}values.push({label,value:Math.round(value*100)/100});}
  return `<div class="data-chart bars-chart" data-chart-scene="bars" data-chart-values="${esc(JSON.stringify(values))}"><div class="chart-tooltip" hidden></div><span class="chart-3d-tag">3D</span></div><div class="chart-caption">${bucket>1?`${bucket} күндік жиынтық`:'Күндік жиынтық'}<span>${dates(state.start)} – ${dates(state.end)}</span></div>${chartDataTable(values,'Нақты мәндерді кестемен көру')}`;
}
function orgChart(rows) {
  const data=state.boot.organizations.filter(o=>state.org==='0'||o.id===Number(state.org)).map(o=>({label:o.name,short:o.short||o.name.slice(0,10),value:Math.round(sum(rows.filter(r=>r.org_id===o.id),'kg')*100)/100}));
  return `<div class="data-chart bars-chart" data-chart-scene="bars" data-chart-values="${esc(JSON.stringify(data))}"><div class="chart-tooltip" hidden></div><span class="chart-3d-tag">3D</span></div><div class="chart-caption">Ұйымдар бойынша жиынтық<span>${dates(state.start)} – ${dates(state.end)}</span></div>${chartDataTable(data,'Ұйымдар бойынша массаны көру')}`;
}
function compositionChart(rows,total) {
  const breakdown={};rows.flatMap(r=>r.items).filter(i=>i.unit!=='l').forEach(i=>breakdown[i.name]=(breakdown[i.name]||0)+i.kg);
  const sorted=Object.entries(breakdown).sort((a,b)=>b[1]-a[1]),rest=sorted.slice(7).reduce((t,e)=>t+e[1],0);
  const data=(rest?[...sorted.slice(0,7),['Басқалары',rest]]:sorted).map(([label,value],i)=>({label,value:Math.round(value*100)/100,color:palette[i%palette.length]}));
  return `<div class="composition-3d"><div class="data-chart ring-chart" data-chart-scene="ring" data-chart-values="${esc(JSON.stringify(data))}"><div class="chart-tooltip" hidden></div><span class="chart-3d-tag">3D</span></div><div class="ring-total"><strong>${fmt(total,1)}</strong><span>кг барлығы</span></div><div class="composition-legend">${data.length?data.map(d=>`<div><span class="color-dot" style="background:${d.color}"></span><span>${esc(d.label)}</span><strong>${fmt(d.value/total*100,1)}%</strong></div>`).join(''):'<p class="muted">Бұл кезеңде қабылданған дерек жоқ.</p>'}</div></div>${chartDataTable(data,'Санаттар бойынша массаны көру')}`;
}

function reportTable(rows) {
  if(!rows.length) return `<div class="empty">${icon('file')}<h3>Есеп табылмады</h3><p>Кезеңді немесе сүзгіні өзгертіңіз.${canCreate()?' Жаңа есеп енгізуге де болады.':''}</p>${canCreate()?'<button class="btn secondary" data-action="create">Жаңа есеп</button>':''}</div>`;
  return `<div class="table-scroll"><table><thead><tr><th>ЕСЕП / ҰЙЫМ</th><th>КҮНІ</th><th class="numeric">МАССА</th><th>МӘРТЕБЕ</th><th>ЖАУАПТЫ</th><th><span class="sr-only">Әрекет</span></th></tr></thead><tbody>${rows.map(r=>`<tr><td><button class="table-link" data-report="${r.id}"><span class="table-icon">${icon('file')}</span><span><strong>${esc(r.org_name)}</strong><small>QW-${String(r.id).padStart(4,'0')} · ${r.items.length} қалдық түрі</small></span></button></td><td class="nowrap">${dates(r.report_date)}</td><td class="numeric"><strong>${fmt(r.kg,1)}</strong> <span class="muted">кг</span>${r.liters?` <span class="muted nowrap">+ ${fmt(r.liters,1)} л</span>`:''}</td><td>${badge(r.status)}</td><td><span class="author-cell"><span class="mini-avatar">${esc(r.author[0])}</span>${esc(r.author)}</span></td><td><button class="icon-btn" data-report="${r.id}" aria-label="QW-${r.id} есебін ашу">${icon('chevron')}</button></td></tr>`).join('')}</tbody></table></div>`;
}
function filteredReports() {
  const term=state.search.toLocaleLowerCase();
  return state.reports.filter(r=>{
    const matchesStatus=state.status==='all'||(state.status==='pending'?['submitted','in_review'].includes(r.status):r.status===state.status);
    const labels=[r.org_name,String(r.id),r.author,...r.items.map(i=>i.name)];
    const searchable=labels.flatMap(label=>[label,QaldyqI18n.text(label,'ru')]).join(' ').toLocaleLowerCase();
    return matchesStatus&&(!term||searchable.includes(term));
  });
}
function reportsView() {
  const rows=filteredReports(), pageSize=8,pages=Math.max(1,Math.ceil(rows.length/pageSize)); state.page=Math.min(state.page,pages);
  const tabs=[['all','Барлығы'],['pending','Тексеруді күтуде'],['accepted','Қабылданған'],['draft','Черновик'],['returned','Қайтарылған']];
  return heading('Қалдық есебі','Бір есептің жолы: тіркеуден — тексерілген дерекке дейін.',createButton())+workerBanner('weigh')+filters()+
    `<div class="workflow-strip">${['draft','submitted','in_review','accepted'].map((s,i)=>`<span><b>${String(i+1).padStart(2,'0')}</b>${statusNames[s]}</span>${i<3?icon('chevron'):''}`).join('')}</div><section class="panel"><div class="report-toolbar"><div class="report-tabs">${tabs.map(([key,label])=>`<button data-status="${key}" class="${state.status===key?'selected':''}">${label}<span>${state.reports.filter(r=>key==='all'||(key==='pending'?['submitted','in_review'].includes(r.status):r.status===key)).length}</span></button>`).join('')}</div><div class="report-tools"><div class="search-input">${icon('search')}<input id="report-search" type="search" placeholder="Ұйым, есеп № немесе қалдық түрі" value="${esc(state.search)}" aria-label="Есептерді іздеу"></div><button class="btn secondary small" data-export="csv">${icon('download')} CSV</button><button class="btn secondary small" data-export="xls">Excel</button><button class="btn secondary small" id="print-report">PDF / Басып шығару</button></div></div><div id="reports-results">${reportTable(rows.slice((state.page-1)*pageSize,state.page*pageSize))}<div class="pagination"><span>${rows.length} есептің ${rows.length?(state.page-1)*pageSize+1:0}–${Math.min(state.page*pageSize,rows.length)} аралығы</span><div><button class="btn secondary small" data-page="${state.page-1}" ${state.page===1?'disabled':''}>Алдыңғы</button><span>${state.page} / ${pages}</span><button class="btn secondary small" data-page="${state.page+1}" ${state.page===pages?'disabled':''}>Келесі</button></div></div></div></section><p class="data-note">${icon('info')} Экспортқа таңдалған кезең, ұйым және қалдық түрі бойынша тек қабылданған жазбалар кіреді. Excel файлында жиынтық және тізілім парақтары бар.</p>`;
}

function organizationsView() {
  const rows=accepted();
  const organizations=state.boot.organizations.filter(o=>state.org==='0'||o.id===Number(state.org));
  return heading('Ұйымдар','Кампустың әр бөлімшесі — бірыңғай есеп жүйесінде.',state.boot.user.role==='admin'?'<button class="btn primary" data-action="add-org">'+icon('plus')+' Ұйым қосу</button>':'')+filters()+
    `<div class="org-grid">${organizations.map(o=>{const reports=state.reports.filter(r=>r.org_id===o.id), approved=rows.filter(r=>r.org_id===o.id), hasSent=reports.some(r=>!['draft','returned'].includes(r.status));return `<article class="panel org-card"><div class="org-top"><span class="org-emblem">${icon(o.kind==='Кофехана'?'leaf':'building')}</span><span class="badge ${hasSent?'accepted':'returned'}"><i></i>${hasSent?'Есеп жіберілді':'Есеп күтілуде'}</span></div><span class="eyebrow">${esc(o.kind)}</span><h2>${esc(o.name)}</h2><div class="org-metrics"><div><strong>${fmt(sum(approved,'kg'),1)} <small>кг</small></strong><span>Қабылданған қалдық</span></div><div><strong>${reports.length}</strong><span>Барлық есеп</span></div></div><button class="text-link" data-org-reports="${o.id}">Есептерін көру ${icon('arrow')}</button></article>`;}).join('')}</div>`+
    `<section class="panel role-panel"><div class="panel-title"><div><h2>Әр рөлдің өз міндеті бар</h2><p>Қолжетімділік серверде тексеріледі</p></div>${icon('check')}</div><div class="role-grid">${[['operator','Өз ұйымының есебін жасайды, түзетеді және жібереді.'],['reviewer','Жіберілген есепті тексеруге алады, қабылдайды не себебімен қайтарады.'],['manager','Жиынтық есептерді, аналитиканы және ықтимал әсерді қарайды.'],['admin','Ұйымдар мен қалдық санаттарын басқарады; есеп процесін орындай алады.']].map(([role,desc])=>`<div><strong>${roleNames[role]}</strong><p>${desc}</p></div>`).join('')}</div></section>`+
    (state.boot.user.role==='admin'?`<section class="panel category-panel"><div class="panel-title"><div><h2>Қалдық санаттары</h2><p>Бағалар мен CO₂ коэффициенттері — команданың жорамалы. Жаңа есептерге қолданылып, есепте сақталады.</p></div><button class="btn secondary" data-action="add-category">${icon('plus')} Санат қосу</button></div><div class="table-scroll"><table><thead><tr><th>САНАТ</th><th>БІРЛІК</th><th>ҚАЙТА ӨҢДЕУГЕ ЖАРАМДЫ</th><th>ӘДЕПКІ ТӘСІЛ</th><th class="numeric">ҚҰН / КГ</th><th class="numeric">КГ CO₂e / КГ</th></tr></thead><tbody>${state.boot.categories.map(c=>`<tr><td>${esc(c.name)}</td><td>${unitNames[c.unit]||'кг'}</td><td>${c.recyclable?'Иә':'Жоқ'}</td><td>${esc(routeName(c.default_route))}</td><td class="numeric">${money(c.cost)}</td><td class="numeric">${fmt(c.co2,2)}</td></tr>`).join('')}</tbody></table></div></section>`:'');
}

function impactView() {
  const p=state.impact;
  const field=(key,label,unit,help,step=1)=>`<label class="calc-field"><span>${label}</span><div><input type="number" data-impact="${key}" value="${p[key]}" min="0" ${key==='reduction'?'max="100"':''} step="${step}" required aria-label="${label}"><span>${unit}</span></div><small>${help}</small></label>`;
  return heading('Әсерді алдын ала есептеңіз.','Пилотқа дейінгі сценарий: болжамдарды өзгертіп, нәтижесін салыстырыңыз.')+
    workerBanner('count')+
    `<div class="scenario-banner">${icon('info')} <div><strong>Бұл — ықтимал әсердің есебі.</strong><span>Өлшенген үнем емес. Нәтиже енгізілген болжамдарға тәуелді; пилотта бастапқы және кейінгі кезеңдер салыстырылады.</span></div></div><div class="impact-layout"><section class="panel calc-inputs"><div class="panel-title"><div><h2>Сценарий параметрлері</h2><p>Айлық бастапқы жағдай</p></div>${icon('chart')}</div><button class="btn secondary full" id="use-actual">Таңдалған кезең дерегінен айлық база алу</button><p class="small muted" id="baseline-note">Бастапқы мәндер — демонстрациялық болжам.</p><div class="calc-grid">${field('kg','Қалдық көлемі','кг / ай','Бастапқы орташа айлық көлем')}${field('cost','Орташа құны','₸ / кг','Сатып алу немесе өзіндік құн')}${field('reduction','Күтілетін азаю','%','Пилотта тексерілетін гипотеза')}${field('co2','Эмиссия коэффициенті','кг CO₂e / кг','Демо баға; дереккөзбен ауыстырыңыз',0.1)}${field('capex','Бастапқы инвестиция','₸','Енгізу, оқыту және жабдықтау')}${field('opex','Айлық шығын','₸ / ай','Қызмет көрсету және қолдау')}</div></section><section class="impact-results" id="impact-results"></section></div><section class="panel formula-panel"><h2>Есептеу әдісі</h2><div class="formula-grid"><div><span>01</span><strong>Болдырылмаған қалдық</strong><p>Айлық масса × азаю үлесі</p></div><div><span>02</span><strong>Айлық таза үнем</strong><p>Болдырылмаған масса × құн − айлық шығын</p></div><div><span>03</span><strong>Өтелу мерзімі</strong><p>Бастапқы инвестиция ÷ айлық таза үнем</p></div></div><p class="small muted">CO₂e бағасы = болдырылмаған масса × коэффициент. Қайта өңдеуге жіберілген масса автоматты түрде «болдырылмаған қалдық» деп есептелмейді. Сценарийде маусымдылық, дисконттау және құн өзгерісі ескерілмеген.</p></section>`+
    `<section class="panel calc-inputs"><div class="panel-title"><div><h2>Еңбек шығынын есептеу</h2><p>Қағаз кесте мен жүйенің айлық уақыт айырмасы · жорамал мәндер</p></div>${icon('clock')}</div><div class="calc-grid">${[['records','Айына өлшем жазбасы','жазба','Барлық ұйым бойынша'],['paper','Қағазда бір жазба','мин','Өлшеу, жазу, қайта көшіру'],['system','Жүйеде бір жазба','мин','Жылдам енгізу режимі'],['merge','Қағаз кестелерді біріктіру','мин / ай','Қолмен жинақтау және тексеру'],['mergeSystem','Жүйеде жиынтық есеп','мин / ай','Экспортты жүктеу және қарау'],['rate','Сағаттық еңбекақы','₸ / сағ','Жорамал мөлшерлеме']].map(([key,label,unit,help])=>`<label class="calc-field"><span>${label}</span><div><input type="number" data-labour="${key}" value="${state.labour[key]}" min="0" step="${key==='paper'||key==='system'?0.1:1}" required aria-label="${label}"><span>${unit}</span></div><small>${help}</small></label>`).join('')}</div><div id="labour-results" class="labour-results"></div><p class="small muted">Формула: үнемделген сағат = (жазба саны × (қағаздағы мин − жүйедегі мин) + біріктіру айырмасы) ÷ 60. Барлық бастапқы мән — жорамал: нақты уақыт пилотта секундомермен өлшенеді.</p></section>`;
}
function updateLabour() {
  const p=state.labour, hours=(p.records*(p.paper-p.system)+(p.merge-p.mergeSystem))/60;
  $('#labour-results').innerHTML=`<div class="result-pair"><div><span>Үнемделетін уақыт · сценарий</span><strong>${fmt(hours,1)} <small>сағ / ай</small></strong></div><div><span>Еңбек құны · сценарий</span><strong>${money(hours*p.rate)} <small>/ ай</small></strong></div><div><span>Жылына</span><strong>${fmt(hours*12,0)} <small>сағ</small></strong></div></div>`;
}
function updateImpact() {
  const p=state.impact, avoided=p.kg*p.reduction/100,gross=avoided*p.cost,net=gross-p.opex,months=net>0?p.capex/net:null;
  $('#impact-results').innerHTML = `<div class="result-primary"><span class="eyebrow light">ЖЫЛДЫҚ ТАЗА ҮНЕМ · СЦЕНАРИЙ</span><h2>${money(net*12)}</h2><p>Айлық таза үнем: ${money(net)}</p><div class="result-divider"></div><div class="result-pair"><div><span>Қалдықтың азаюы</span><strong>${fmt(avoided*12,1)} <small>кг / жыл</small></strong></div><div><span>CO₂e азаю бағасы</span><strong>${fmt(avoided*p.co2*12/1000,2)} <small>т / жыл</small></strong></div></div></div><div class="panel payback"><span class="insight-icon mint">${icon('clock')}</span><div><p>Инвестицияның өтелуі</p><strong>${months===null?'Өтелмейді':p.capex===0?'Бастапқы инвестиция жоқ':fmt(months,1)+' ай'}</strong><span>${net<=0?'Таза үнем оң емес. Сценарийді қайта қараңыз.':'Айлық жалпы үнем: '+money(gross)}</span></div></div><div class="panel impact-note"><span class="tiny-label">ПИЛОТТА ҚАЛАЙ ТЕКСЕРЕМІЗ?</span><p>Алдымен 2 апта бастапқы дерек жиналады. Келесі 2 аптада өндіріс жоспары түзетіледі. Келуші санына шаққандағы <strong>кг / 100 порция</strong> көрсеткіші салыстырылады.</p><span class="badge accepted"><i></i>ЦУР 12.3-пен байланысты мақсат</span></div>`;
}
function bindImpact() {
  updateImpact(); updateLabour();
  $$('[data-labour]').forEach(el=>el.addEventListener('input',()=>{if(!el.checkValidity()||el.value==='')return;state.labour[el.dataset.labour]=Number(el.value);updateLabour();QaldyqI18n.apply($('#labour-results'));}));
  $$('[data-impact]').forEach(el=>el.addEventListener('input',()=>{
    if(!el.checkValidity()||el.value===''){el.setAttribute('aria-invalid','true');return;}
    el.removeAttribute('aria-invalid');state.impact[el.dataset.impact]=Number(el.value);updateImpact();
  }));
  $('#use-actual').addEventListener('click',()=>{
    const rows=accepted(),kg=sum(rows,'kg');if(!kg)return toast('Таңдалған кезеңде қабылданған дерек жоқ.',true);
    const days=(new Date(state.end+'T12:00:00')-new Date(state.start+'T12:00:00'))/86400000+1;
    state.impact.kg=Math.round(kg/days*30);state.impact.cost=Math.round(sum(rows,'cost')/kg);state.impact.co2=Math.round(sum(rows,'co2')/kg*100)/100;
    ['kg','cost','co2'].forEach(key=>$(`[data-impact="${key}"]`).value=state.impact[key]);
    $('#baseline-note').textContent=`${state.start}–${state.end}: ${fmt(kg,1)} кг / ${days} күн × 30 күн. Құн мен CO₂ — массамен өлшенген орташа баға. Демо деректер.`;updateImpact();
  });
}

function guideView() {
  const criteria=[['Инновациялық · 20 балл','QR, офлайн PWA, екі тіл, порция ұсынысы және ауытқу ережесі бар. AI-енгізу, OCR, Telegram-бот және таразы API-і қосылмаған.'],['Практикалық қолданылуы · 20 балл','Толық цикл: форма → тексеру → тізілім → аналитика → есеп. Ұйымдар мен қалдық түрлері АТУ кестелерінің үлгісі бойынша берілген.'],['Экономикалық әсер · 15 балл','CAPEX, OPEX, таза үнем мен өтелудің ашық есебі. Еңбек уақытының үнемі пилотта өлшенеді.'],['Экологиялық әсер · 15 балл','Қалдық массасы, қайта өңдеуге жарамды үлес, CO₂e бағасы және ЦУР 12.3. Коэффициенттер — команданың жорамалы.'],['Зерттеу сапасы · 10 балл','Аналогтар, жорамалдар мен тәуекелдер зерттеу құжатында берілген. АТУ-да сұхбат пен өлшеу жүргізілген жоқ.'],['Презентация және қорғау · 10 балл','5 минут сөз, 3 минут сұрақ, 12 слайдқа дейін. Тірі демо жалпы уақытқа кіреді.'],['Командалық жұмыс · 10 балл','NOVA · 3 қатысушы. Рөлдер мен әр қатысушының үлесін команда өзі көрсетеді.']];
  return heading('Qaldyq — жоба паспорты','Трек 1 · Digital Food Waste Management System for University Campuses')+
    `<section class="project-intro panel"><span class="pill">ATU · Smart Food Industries 2026</span><h2>Кампус қалдықтарының<br>бірыңғай цифрлық есебі.</h2><p>Қызметкер қалдықты тіркейді. Тексеруші деректі растайды. Басшылық ортақ көріністі қарап, өндіріс жоспарын өзгертуге негіз алады.</p><div class="project-tags"><span>Web + Mobile</span><span>Submission workflow</span><span>ESG analytics</span><span>ЦУР 12.3</span></div></section><section class="panel"><div class="panel-title"><div><h2>Бағалау критерийлеріне сәйкестік</h2><p>Регламент бойынша 7 критерий, жалпы 100 балл.</p></div><a class="text-link" href="https://atu-fit.github.io/SmartFoodIndustries/#criteria" target="_blank" rel="noopener">Іс-шара сайты ${icon('arrow')}</a></div><div class="criteria-grid">${criteria.map(([name,desc])=>`<article><div><h3>${name}</h3></div><p>${desc}</p></article>`).join('')}</div></section><div class="guide-grid"><section class="panel"><div class="panel-title"><h2>60 секундтық демо</h2>${icon('clock')}</div><ol class="demo-steps"><li><strong>00–15 сек.</strong><span>Қызметкер жаңа есепке екі қалдық түрін енгізіп, жібереді.</span></li><li><strong>15–30 сек.</strong><span>Тексеруші есепті тексеруге алып, қабылдайды немесе себебімен қайтарады.</span></li><li><strong>30–45 сек.</strong><span>Басшылық дашбордтан қабылданған массаны, құрамды және ұйымдарды көреді.</span></li><li><strong>45–60 сек.</strong><span>Калькуляторда болжамды үнем мен өтелу көрсетіліп, есеп экспортталады.</span></li></ol></section><section class="panel"><div class="panel-title"><h2>Пилотқа дейінгі қадамдар</h2>${icon('leaf')}</div><ol class="demo-steps"><li><strong>1-апта</strong><span>Асханадағы өлшеу тәртібін, санаттарды, бағалар мен жауаптыларды келісу.</span></li><li><strong>2–3-апта</strong><span>Екі асханада бастапқы кезең: таразы өлшемі мен цифрлық есепті салыстыру.</span></li><li><strong>4–5-апта</strong><span>Мәзір мен порция жоспарын түзету, бір порцияға шаққандағы өзгерісті өлшеу.</span></li><li><strong>Қорытынды</strong><span>Нақты үнемді, дерек толықтығын және енгізу шығынын бағалау.</span></li></ol></section></div><section class="panel limitations"><h2>Болжамдар мен шектеулер</h2><p>Барлық бастапқы есептер синтетикалық. AI моделі қолданылмайды: ауытқу белгісі медианаға негізделген қарапайым ереже. CO₂ және баға коэффициенттері демонстрациялық. Экономикалық әсер — тек сценарий. Қайта өңдеу фактісін растау үшін қабылдаушы ұйымның құжаты қажет.</p><p>Бұл нұсқа жергілікті демонстрацияға арналған. Кампус пилотына дейін жеке аккаунттар, HTTPS, резервтік көшіру, фотоның сақтау мерзімі және серверді тұрақты орналастыру қажет. Тағамды тарату не қайта пайдалануға рұқсат беру жүйенің міндетіне кірмейді.</p><p class="small muted">Декларация: прототиптің негізі хакатонға дейін дайындалды. Код, мәтін және екі иллюстрация генеративті ЖИ көмегімен жасалды. Ашық кітапханалар: Three.js және qrcode-generator (MIT). Хакатон күнгі өзгерістер репозиторий тарихында көрсетіледі.</p></section>`;
}

function bindCommon() {
  bindStudio();
  $$('[data-action="create"]').forEach(el=>el.addEventListener('click',()=>openReportForm()));
  $$('[data-view-action]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.viewAction)));
  $$('[data-report]').forEach(el=>el.addEventListener('click',()=>openReport(Number(el.dataset.report))));
  $$('[data-action="pending"]').forEach(el=>el.addEventListener('click',()=>{navigate('reports');state.status='pending';renderMain();}));
  $$('[data-period]').forEach(el=>el.addEventListener('click',()=>{
    state.period=el.dataset.period;Object.assign(state,periodRange(state.period,state.boot.today,state.boot.demo_date));state.page=1;loadData();
  }));
  ['start','end','org','category'].forEach(key=>{const el=$('#filter-'+key);if(el)el.addEventListener('change',()=>{
    if(!el.value || !el.checkValidity()){toast('Кезең күндерін дұрыс көрсетіңіз.',true);return;}
    state[key]=el.value;if(key==='start'||key==='end')state.period='custom';
    if(key==='org'&&!orgCategories(state.org).some(c=>String(c.id)===state.category))state.category='0';
    state.page=1;loadData();
  });});
  $$('[data-status]').forEach(el=>el.addEventListener('click',()=>{state.status=el.dataset.status;state.page=1;renderMain();}));
  $$('[data-page]').forEach(el=>el.addEventListener('click',()=>{state.page=Number(el.dataset.page);renderMain();}));
  const search=$('#report-search');if(search)search.addEventListener('input',()=>{
    const cursor=search.selectionStart;state.search=search.value;state.page=1;renderMain();const next=$('#report-search');next.focus();try{next.setSelectionRange(cursor,cursor);}catch{}
  });
  $$('[data-export]').forEach(el=>el.addEventListener('click',()=>{window.location.href='/api/export?'+queryString()+'&format='+el.dataset.export;}));
  const print=$('#print-report');if(print)print.addEventListener('click',()=>openPrintSummary());
  $$('[data-org-reports]').forEach(el=>el.addEventListener('click',()=>{state.org=el.dataset.orgReports;state.category='0';state.view='reports';$$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view==='reports'));loadData();}));
  const addOrg=$('[data-action="add-org"]');if(addOrg)addOrg.addEventListener('click',()=>openRegistry('organizations'));
  const addCat=$('[data-action="add-category"]');if(addCat)addCat.addEventListener('click',()=>openRegistry('categories'));
}

function bindStudio() {
  const scenes = {
    campus: {src:'/campus-3d-v2.png',alt:'Жасыл шатыры мен сұрыптау контейнерлері бар кампустың 3D иллюстрациясы',caption:'01 / Кампус моделі'},
    cycle: {src:'/cycle-3d-v2.png',alt:'Қайта өңдеу айналымы мен өсімдіктің 3D иллюстрациясы',caption:'02 / Ресурс циклі'},
  };
  $$('[data-scene]').forEach(button => button.addEventListener('click', () => {
    const scene = scenes[button.dataset.scene], image = $('[data-scene-image]');
    if (!image) return;
    image.src=scene.src; image.alt=scene.alt;
    image.classList.toggle('cycle-shot',button.dataset.scene==='cycle');
    $('[data-scene-caption]').textContent=scene.caption;
    $$('[data-scene]').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
  }));
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  $$('[data-parallax]').forEach(card => {
    card.addEventListener('pointermove', e => {
      if(motion.matches || e.pointerType==='touch') return;
      const rect=card.getBoundingClientRect();
      card.style.setProperty('--tilt-y',`${((e.clientX-rect.left)/rect.width-.5)*9}deg`);
      card.style.setProperty('--tilt-x',`${-((e.clientY-rect.top)/rect.height-.5)*6}deg`);
    });
    card.addEventListener('pointerleave',()=>{card.style.setProperty('--tilt-y','0deg');card.style.setProperty('--tilt-x','0deg');});
  });
}

function openDialog(content, wide=false) {
  const dialog=$('#dialog');dialog.className=wide?'wide':'';dialog.innerHTML=content;
  QaldyqI18n.apply(dialog);
  if(!dialog.open)dialog.showModal();
  $$('[data-close]',dialog).forEach(el=>el.addEventListener('click',()=>dialog.close()));
  dialog.onclick=e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}};
}
function dialogHeading(title, subtitle='') { return `<div class="dialog-heading"><div><span class="eyebrow">QALDYQ · ЕСЕП</span><h2 id="dialog-title">${title}</h2>${subtitle?`<p class="muted">${subtitle}</p>`:''}</div><div class="dialog-language-tools">${QaldyqI18n.switcher()}<button class="icon-btn" data-close aria-label="Жабу">${icon('close')}</button></div></div>`; }

async function openReport(id) {
  try {
    const r=await api('/api/reports/'+id),editable=canCreate()&&['draft','returned'].includes(r.status);
    const total=sum(r.items.filter(i=>i.unit!=='l'),'kg'),liters=sum(r.items.filter(i=>i.unit==='l'),'kg'),cost=r.items.reduce((s,i)=>s+i.kg*i.cost,0);
    const comparable=state.reports.filter(x=>x.status==='accepted'&&x.org_id===r.org_id&&x.id!==r.id).map(x=>x.kg).sort((a,b)=>a-b);
    const median=comparable.length?comparable.length%2?comparable[Math.floor(comparable.length/2)]:(comparable[comparable.length/2-1]+comparable[comparable.length/2])/2:0;
    const unusual=comparable.length>=5&&total>median*2;
    openDialog(dialogHeading(`QW-${String(id).padStart(4,'0')}`,`${esc(orgName(r.org_id))} · ${dates(r.report_date)}`)+`<div class="detail-body"><div class="detail-summary">${badge(r.status)}<strong>${fmt(total,1)} кг${liters?' + '+fmt(liters,1)+' л':''}</strong><span>${money(cost)} · құн бағасы</span></div>${unusual?`<div class="anomaly">${icon('info')} Масса осы ұйымның таңдалған кезеңдегі ${comparable.length} қабылданған есебінің медианасынан 2 еседен жоғары (${fmt(median,1)} кг). Өлшемді тексеріңіз. Бұл — ереже бойынша белгі.</div>`:''}<div class="table-scroll"><table><thead><tr><th>ҚАЛДЫҚ ТҮРІ</th><th class="numeric">САНЫ</th><th>КӘДЕГЕ ЖАРАТУ ТӘСІЛІ</th><th class="numeric">ҚҰН БАҒАСЫ</th></tr></thead><tbody>${r.items.map(i=>`<tr><td>${esc(i.name)}</td><td class="numeric nowrap">${fmt(i.kg,2)} ${unitNames[i.unit]||'кг'}</td><td>${esc(routeName(i.route))}</td><td class="numeric">${money(i.kg*i.cost)}</td></tr>`).join('')}</tbody></table></div>${r.portions?`<div class="detail-note"><strong>${fmt(r.portions)} порция · ${fmt(total/r.portions*100,2)} кг / 100 порция</strong></div>`:''}${r.dishes?.length?`<div class="table-scroll"><table><thead><tr><th>ТАҒАМ</th><th>ДАЙЫН</th><th>САТЫЛДЫ</th><th>АРТЫЛДЫ</th><th>КГ</th></tr></thead><tbody>${r.dishes.map(d=>`<tr><td data-i18n-skip>${esc(d.name)}</td><td>${d.prepared}</td><td>${d.served}</td><td>${d.leftover}</td><td>${fmt(d.leftover_kg,2)}</td></tr>`).join('')}</tbody></table></div>`:''}${r.note?`<div class="detail-note"><span class="tiny-label">ЕСКЕРТПЕ</span><p>${esc(r.note)}</p></div>`:''}${r.photo?`<img class="report-photo" src="${esc(r.photo)}" alt="Есепке тіркелген қалдық фотосы">`:''}<h3 class="history-title">Өзгерістер тарихы</h3><ol class="history">${r.history.map(h=>`<li><span class="history-dot"></span><div><strong>${esc({created:'Есеп жасалды',edited:'Есеп түзетілді',...statusNames}[h.action])}</strong><span>${esc(h.name)} · ${localTime(h.created_at)}</span>${h.comment?`<p>${esc(h.comment)}</p>`:''}</div></li>`).join('')}</ol>${canReview()&&r.status==='in_review'?'<label for="review-comment">Тексеруші пікірі <span class="muted">(қайтарғанда міндетті)</span></label><textarea id="review-comment" rows="3" maxlength="2000" placeholder="Есепті нақтылау қажет болса, себебін жазыңыз"></textarea>':''}<p class="form-error" id="detail-error" role="alert"></p></div><div class="dialog-footer"><button class="btn secondary" data-close>Жабу</button><div>${editable?'<button class="btn secondary" id="edit-report">Өңдеу</button><button class="btn primary" data-transition="submitted">Тексеруге жіберу</button>':''}${canReview()&&r.status==='submitted'?'<button class="btn primary" data-transition="in_review">Тексеруге алу</button>':''}${canReview()&&r.status==='in_review'?'<button class="btn danger" data-transition="returned">Қайтару</button><button class="btn primary" data-transition="accepted">'+icon('check')+' Қабылдау</button>':''}</div></div>`,true);
    const edit=$('#edit-report');if(edit)edit.addEventListener('click',()=>openReportForm(r));
    $$('[data-transition]').forEach(el=>el.addEventListener('click',async()=>{
      const buttons=$$('[data-transition]');buttons.forEach(b=>b.disabled=true);
      try {await api(`/api/reports/${id}/transition`,{method:'POST',body:{status:el.dataset.transition,comment:$('#review-comment')?.value||'',updated_at:r.updated_at}});toast('Есеп мәртебесі жаңартылды.');await loadData();await openReport(id);}
      catch(error){$('#detail-error').textContent=error.message;buttons.forEach(b=>b.disabled=false);}
    }));
  } catch(error){toast(error.message,true);}
}

function wasteTypeFields(p) {
  return `<label>Қалдық түрінің атауы<input id="${p}-name" minlength="2" maxlength="120" placeholder="Мысалы, шай қалдығы"></label><div class="form-grid"><label>Өлшем бірлігі<select id="${p}-unit"><option value="kg">кг</option><option value="l">л</option></select></label><label>Әдепкі кәдеге жарату тәсілі<select id="${p}-route">${routeList().map(r=>`<option value="${esc(r.code)}">${esc(r.name)}</option>`).join('')}</select></label></div><label class="check-line"><input type="checkbox" id="${p}-recyclable"> <span>Қайта өңдеуге жарамды</span></label>`;
}
function wasteTypeBody(p) { return {name:$(`#${p}-name`).value,unit:$(`#${p}-unit`).value,default_route:$(`#${p}-route`).value,recyclable:$(`#${p}-recyclable`).checked}; }

function openReportForm(existing=null) {
  const isEdit=!!existing?.id;
  let photo=existing?.photo||null, baseTotals={totals:[],same_day_reports:0};
  const requestId=existing?.request_id||uuid();
  const defaultOrg=state.boot.user.org_id||Number(state.org)||state.boot.organizations[0].id;
  const formOrg=()=>Number($('#form-org')?.value||existing?.org_id||defaultOrg);
  const catById=id=>state.boot.categories.find(c=>c.id===Number(id));
  const catOptions=(org,selected)=>{const cats=orgCategories(org),extra=catById(selected);return (extra&&!cats.includes(extra)?[...cats,extra]:cats).map(c=>`<option value="${c.id}" ${c.id===selected?'selected':''}>${esc(c.name)}</option>`).join('');};
  const row=(item={},org=existing?.org_id||defaultOrg)=>{const cat=catById(item.category_id)||orgCategories(org)[0];return `<div class="waste-row"><label><span>Қалдық түрі</span><select name="category" required>${catOptions(org,cat?.id)}</select></label><label><span>Саны, <b data-unit>${unitNames[cat?.unit]||'кг'}</b></span><input name="kg" type="number" inputmode="decimal" min="0.01" max="10000" step="0.01" value="${item.kg||''}" placeholder="0.00" required></label><label><span>Кәдеге жарату тәсілі</span><select name="route">${routeList().map(r=>`<option value="${esc(r.code)}" ${(item.route||cat?.default_route||'tbo')===r.code?'selected':''}>${esc(r.name)}</option>`).join('')}</select></label><label><span>Пайда болу кезеңі</span><select name="stage">${Object.entries(stageNames).map(([key,label])=>`<option value="${key}" ${(item.stage||'other')===key?'selected':''}>${label}</option>`).join('')}</select></label><button type="button" class="icon-btn remove-row" aria-label="Қалдық жолын жою">${icon('close')}</button></div>`;};
  openDialog(dialogHeading(isEdit?'Есепті өңдеу':'Жаңа қалдық есебі','Массаны таразы көрсеткіші бойынша енгізіңіз. Өлшем бірлігі қалдық түріне байланысты.')+`<form id="report-form"><div class="detail-body"><div class="form-grid"><label>Ұйым<select id="form-org" ${state.boot.user.role==='operator'||isEdit?'disabled':''}>${state.boot.organizations.map(o=>`<option value="${o.id}" ${o.id===(existing?.org_id||defaultOrg)?'selected':''}>${esc(o.name)}</option>`).join('')}</select></label><label>Есеп күні<input id="form-date" type="date" value="${existing?.report_date||state.boot.today||state.boot.demo_date}" max="${state.boot.today||state.boot.demo_date}" min="2020-01-01" required></label></div><p class="small muted">Жауапты тұлға: <strong data-i18n-skip>${esc(state.boot.user.name)}</strong></p><div class="form-section-title"><h3>Қалдық құрамы</h3><span class="small muted">Әр түрге жеке жол</span></div><div id="waste-rows">${((existing?.items||[]).filter(i=>!i.locked).length?existing.items.filter(i=>!i.locked):[{}]).map(item=>row(item)).join('')}</div>${(existing?.items||[]).some(i=>i.locked)?`<p class="data-note">${icon('info')} Қоймадан есептен шығарылған ${existing.items.filter(i=>i.locked).length} өлшем осы есепте сақталады және бұл формада өзгертілмейді.</p>`:''}<button class="text-link add-row" id="add-row" type="button">${icon('plus')} Қалдық түрін қосу</button> <button class="text-link add-row" id="new-type-toggle" type="button">${icon('plus')} Тізімде жоқ түрді қосу</button><div id="new-type-panel" class="new-type-panel" hidden>${wasteTypeFields('new-type')}<p class="form-error" id="new-type-error" role="alert"></p><button type="button" class="btn secondary small" id="new-type-save">Ұйым тізіміне қосу</button></div><div class="form-total"><span>Жалпы масса</span><strong id="form-total">0 кг</strong></div><p class="data-note" id="duplicate-warning" role="status" hidden></p><div id="period-totals" class="period-totals"></div>${foodFormMarkup(existing)}<p class="small muted" id="form-per100"></p><label for="form-note">Ескертпе</label><textarea id="form-note" rows="3" maxlength="2000" placeholder="Қалдықтың пайда болу себебі, өлшем туралы қосымша ақпарат">${esc(existing?.note||'')}</textarea><label class="photo-upload" for="form-photo">${icon('camera')}<div><strong>Фото тіркеу</strong><span>JPEG, PNG, WebP · 2 МБ-қа дейін · міндетті емес</span></div><input id="form-photo" type="file" accept="image/jpeg,image/png,image/webp"></label><div id="photo-preview">${photo?'<span class="small">Фото тіркелген</span> <button type="button" class="text-link" id="remove-photo">Өшіру</button>':''}</div><p id="local-save-note" role="status">Форма толтырылған сайын құрылғыға сақталады.</p><p class="form-error" id="form-error" role="alert"></p></div><div class="dialog-footer"><button type="button" class="btn secondary" data-close>Бас тарту</button><div class="form-send-options">${!isEdit?'<label class="sr-only" for="save-mode">Сақтау тәсілі</label><select id="save-mode"><option value="draft">Черновикке сақтау</option><option value="submit">Тексеруге жіберу</option></select>':''}<button type="button" class="btn secondary" id="save-local">Құрылғыға сақтау</button><button type="submit" class="btn primary">${icon('check')} Сақтау / жіберу</button></div></div></form>`,true);
  if(!isEdit&&existing?.submit)$('#save-mode').value='submit';
  // Day and month totals per waste type: saved records of this organization plus the rows being typed.
  const updateTotal=()=>{
    const live={};let kg=0,liters=0;
    $$('.waste-row').forEach(el=>{const cat=catById($('[name="category"]',el).value),value=Number($('[name="kg"]',el).value)||0;if(!cat)return;if(cat.unit==='l')liters+=value;else kg+=value;live[cat.id]=(live[cat.id]||0)+value;});
    const portions=Number($('#form-portions').value);
    $('#form-total').textContent=fmt(kg,2)+' кг'+(liters?' + '+fmt(liters,2)+' л':'');
    $('#form-per100').textContent=portions?'100 порцияға: '+fmt(kg/portions*100,2)+' кг':'Порция саны енгізілсе, 100 порцияға шаққандағы көрсеткіш шығады.';
    const ids=[...new Set([...baseTotals.totals.map(t=>t.category_id),...Object.keys(live).map(Number)])];
    $('#period-totals').innerHTML=ids.length?`<div class="table-scroll"><table><thead><tr><th>ҚАЛДЫҚ ТҮРІ</th><th class="numeric">КҮН ЖИЫНТЫҒЫ</th><th class="numeric">АЙ ЖИЫНТЫҒЫ</th></tr></thead><tbody>${ids.map(id=>{const base=baseTotals.totals.find(t=>t.category_id===id)||{day:0,month:0},cat=catById(id),unit=unitNames[cat?.unit||base.unit]||'кг',add=live[id]||0;return `<tr><td>${esc(cat?.name||base.name||'')}</td><td class="numeric nowrap">${fmt(base.day+add,2)} ${unit}</td><td class="numeric nowrap">${fmt(base.month+add,2)} ${unit}</td></tr>`;}).join('')}</tbody></table></div>`:'';
  };
  const loadTotals=async()=>{
    const day=$('#form-date').value;if(!day)return;
    let data={totals:[],same_day_reports:0};
    try{if(navigator.onLine)data=await api('/api/totals?'+new URLSearchParams({org:formOrg(),date:day,exclude:existing?.id||0}));}catch{/* Totals then show only the rows being typed. */}
    if(!$('#report-form'))return;
    baseTotals=data;const warning=$('#duplicate-warning');warning.hidden=!data.same_day_reports;
    warning.textContent=data.same_day_reports?`Бұл күнге ${data.same_day_reports} есеп тіркелген. Жазба қайталанбағанын тексеріңіз.`:'';updateTotal();
  };
  $('#form-portions').addEventListener('input',updateTotal);
  const syncRow=el=>{const cat=catById($('[name="category"]',el).value);if(!cat)return;$('[data-unit]',el).textContent=unitNames[cat.unit]||'кг';$('[name="route"]',el).value=cat.default_route;};
  const bindRows=()=>{$$('.remove-row').forEach(button=>button.onclick=()=>{if($$('.waste-row').length===1)return toast('Кемінде бір қалдық жолы қажет.',true);button.closest('.waste-row').remove();updateTotal();saveLocalDraft();});$$('.waste-row').forEach(el=>{$('[name="category"]',el).onchange=()=>{syncRow(el);updateTotal();};});$$('input[name="kg"]').forEach(input=>input.oninput=updateTotal);updateTotal();};bindRows();
  $('#add-row').addEventListener('click',()=>{if($$('.waste-row').length>=30)return toast('Ең көбі 30 жол.',true);$('#waste-rows').insertAdjacentHTML('beforeend',row({},formOrg()));bindRows();});
  $('#form-date').addEventListener('change',loadTotals);
  $('#form-org').addEventListener('change',()=>{$('#waste-rows').innerHTML=row({},formOrg());bindRows();loadTotals();});
  $('#new-type-toggle').onclick=()=>{const panel=$('#new-type-panel');panel.hidden=!panel.hidden;if(!panel.hidden)$('#new-type-name').focus();};
  $('#new-type-name').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();$('#new-type-save').click();}});
  $('#new-type-save').onclick=async()=>{
    const button=$('#new-type-save'),org=formOrg();button.disabled=true;$('#new-type-error').textContent='';
    try{
      const result=await api('/api/categories',{method:'POST',body:{...wasteTypeBody('new-type'),org_id:org}});
      const fresh=await api('/api/bootstrap');state.boot.categories=fresh.categories;state.boot.org_categories=fresh.org_categories;
      $$('.waste-row select[name="category"]').forEach(select=>{select.innerHTML=catOptions(org,Number(select.value));});
      const rows=$$('.waste-row'),last=rows[rows.length-1],markup=row({category_id:result.id},org);
      if(last&&!Number($('[name="kg"]',last).value))last.outerHTML=markup;else $('#waste-rows').insertAdjacentHTML('beforeend',markup);
      bindRows();$('#new-type-name').value='';$('#new-type-panel').hidden=true;toast('Қалдық түрі ұйым тізіміне қосылды.');saveLocalDraft();
    }catch(error){$('#new-type-error').textContent=error.network?'Жаңа түр қосу үшін сервермен байланыс қажет.':error.message;}
    finally{button.disabled=false;}
  };
  loadTotals();
  const saveLocalDraft=bindFoodForm({...existing,request_id:requestId},()=>photo);
  $('#save-local').onclick=async()=>{try{clearTimeout(localDraftTimer);await QStore.set('draft:'+state.boot.user.id,captureForm({...existing,request_id:requestId},photo));await refreshOfflineStatus();toast('Форма осы құрылғыға сақталды.');}catch{toast('Құрылғы жадына сақтау орындалмады.',true);}};
  const clearPhoto=()=>{photo=null;$('#form-photo').value='';$('#photo-preview').innerHTML='';saveLocalDraft();};
  if($('#remove-photo'))$('#remove-photo').onclick=clearPhoto;
  $('#form-photo').addEventListener('change',async e=>{
    const file=e.target.files[0];if(!file)return;
    if(file.size>2000000||!['image/jpeg','image/png','image/webp'].includes(file.type)){e.target.value='';toast('Фото JPEG, PNG немесе WebP, 2 МБ-қа дейін болсын.',true);return;}
    try {photo=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Фото оқылмады.'));reader.readAsDataURL(file);});$('#photo-preview').innerHTML=`<img class="photo-thumb" src="${esc(photo)}" alt="Тіркелетін фото"><button type="button" class="text-link" id="remove-photo">Фотоны өшіру</button>`;$('#remove-photo').onclick=clearPhoto;saveLocalDraft();}catch(error){toast(error.message,true);}
  });
  $('#report-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=$('button[type="submit"]',e.target);button.disabled=true;
    clearTimeout(localDraftTimer);
    const payload={...captureForm(existing,photo),request_id:requestId,...(!isEdit?{submit:$('#save-mode').value==='submit'}:{})};
    const path='/api/reports'+(isEdit?'/'+existing.id:''),method=isEdit?'PUT':'POST';
    try {
      if(!navigator.onLine)throw Object.assign(new Error('offline'),{network:true});
      const result=await api(path,{method,body:payload});
      if(existing?._queueKey)await QStore.remove(existing._queueKey);
      await QStore.del('draft:'+state.boot.user.id);await refreshOfflineStatus();
      toast(payload.submit?'Есеп тексеруге жіберілді.':'Черновик сақталды.');await loadData();await openReport(isEdit?existing.id:result.id);
    } catch(error){
      if(error.network){try{await queueReport(payload,isEdit?existing:null);$('#dialog').close();toast('Есеп құрылғыға сақталды. Байланыс қосылғанда жіберіледі.');}catch{$('#form-error').textContent='Құрылғыға сақтау орындалмады. Форманы жаппай, бос орынды тексеріңіз.';button.disabled=false;}}
      else {$('#form-error').textContent=error.message;button.disabled=false;}
    }
  });
}

function openRegistry(type) {
  const org=type==='organizations';
  openDialog(dialogHeading(org?'Ұйым қосу':'Қалдық санатын қосу')+`<form id="registry-form"><div class="detail-body">${org?'<label>Атауы<input id="registry-name" required minlength="2" maxlength="120"></label><label>Қысқа атауы <span class="muted">(диаграммаға, 12 таңбаға дейін)</span><input id="registry-short" maxlength="12"></label><label>Ұйым түрі<select id="registry-kind"><option>Асхана</option><option>Кофехана</option><option>Қонақүй</option><option>Кафедра</option><option>Бөлімше</option></select></label>':wasteTypeFields('registry')+`<label>Ұйым<select id="registry-org"><option value="0">Барлық ұйымдар</option>${state.boot.organizations.map(o=>`<option value="${o.id}">${esc(o.name)}</option>`).join('')}</select></label><label>Құн бағасы, ₸ / кг<input type="number" min="0" step="0.01" id="registry-cost" required></label><label>Эмиссия бағасы, кг CO₂e / кг<input type="number" min="0" max="1000" step="0.01" id="registry-co2" required></label><p class="small muted">Коэффициент жаңа есепте сақталады. Пилотта дереккөзі мен есеп шекарасын тіркеңіз.</p>`}<p class="form-error" id="registry-error" role="alert"></p></div><div class="dialog-footer"><button type="button" class="btn secondary" data-close>Бас тарту</button><button class="btn primary" type="submit">Сақтау</button></div></form>`);
  $('#registry-form').addEventListener('submit',async e=>{e.preventDefault();const b=$('button[type=submit]',e.target);b.disabled=true;try{await api('/api/'+type,{method:'POST',body:org?{name:$('#registry-name').value,short:$('#registry-short').value,kind:$('#registry-kind').value}:{...wasteTypeBody('registry'),org_id:Number($('#registry-org').value),cost:$('#registry-cost').value,co2:$('#registry-co2').value}});const updated=await api('/api/bootstrap');state.boot=updated;$('#dialog').close();await loadData();toast('Анықтамалық жаңартылды.');}catch(error){$('#registry-error').textContent=error.message;b.disabled=false;}});
}

function openPrintSummary() {
  const old=$('#print-area');if(old)old.remove();
  const rows=state.reports,approved=accepted();
  const section=document.createElement('section');section.id='print-area';
  section.innerHTML=`<h1>Qaldyq · Қалдық есебі</h1><p>${state.start} – ${state.end} · ${state.org==='0'?'Барлық ұйымдар':esc(orgName(state.org))}</p><p>Демо деректер. Қабылданған қалдық: ${fmt(sum(approved,'kg'),2)} кг. Құн бағасы: ${money(sum(approved,'cost'))}. CO₂e бағасы: ${fmt(sum(approved,'co2'),2)} кг.</p><p>Төмендегі тізім барлық мәртебені қамтиды. Аналитика тек қабылданған есептерден есептеледі.</p><table><thead><tr><th>№</th><th>Ұйым</th><th>Күні</th><th>Кг</th><th>Мәртебе</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.id}</td><td>${esc(r.org_name)}</td><td>${r.report_date}</td><td>${fmt(r.kg,2)}</td><td>${statusNames[r.status]}</td></tr>`).join('')}</tbody></table><p>Құн мен CO₂ коэффициенттері демонстрациялық. Құжатты браузердің басып шығару терезесінен PDF ретінде сақтауға болады.</p>`;
  document.body.append(section);QaldyqI18n.apply(section);window.print();
}

boot();
