'use strict';
let featureStarted=false, syncBusy=false, localDraftTimer, foodLoadSequence=0;
const weekNames=['Дүйсенбі','Сейсенбі','Сәрсенбі','Бейсенбі','Жұма','Сенбі','Жексенбі'];

async function featuresBoot(){
  const safe={...state.boot,csrf:''};
  if(navigator.onLine){await QStore.set('boot',safe);await QStore.set('active-user',safe.user.id);}
  if(!featureStarted){
    featureStarted=true;
    if('serviceWorker' in navigator){try{await navigator.serviceWorker.register('/sw.js');}catch{toast('Интернетсіз ашу қолдауы іске қосылмады.',true);}}
    window.addEventListener('online',()=>{refreshOfflineStatus();syncReports();});
    window.addEventListener('offline',refreshOfflineStatus);
    setInterval(()=>{if(state.boot&&navigator.onLine){pollNotifications();syncReports();}},30000);
    navigator.serviceWorker?.addEventListener('message',event=>{if(event.data.type==='synced'){refreshOfflineStatus();if(event.data.sent)loadData();}if(event.data.type==='notifications')navigate('notifications');});
  }
  await refreshOfflineStatus();pollNotifications();syncReports();
}

async function refreshOfflineStatus(){
  if(!state.boot)return;
  const tasks=(await QStore.tasks()).filter(t=>t.user===state.boot.user.id);
  const draft=await QStore.get('draft:'+state.boot.user.id);
  const connected=navigator.onLine&&state.connected!==false;
  let el=$('#offline-status');
  if(!el){el=document.createElement('div');el.id='offline-status';el.className='offline-status';$('.content-wrap').insertBefore(el,$('#main'));}
  el.innerHTML=`<span class="connection ${connected?'online':'offline'}"><i></i>${connected?'Байланыс бар':'Интернетсіз режим'}</span><span>${tasks.length?`${tasks.length} есеп жіберуді күтуде`:'Телефонға сақтау дайын'}</span><div><button class="text-link" id="queue-open">Жіберу кезегі${tasks.length?' · '+tasks.length:''}</button>${draft?'<button class="text-link" id="draft-resume">Сақталған форманы ашу</button>':''}</div>`;
  $('#queue-open').onclick=openQueue;
  if($('#draft-resume'))$('#draft-resume').onclick=()=>openReportForm({...draft,_local:true});
}

async function queueReport(payload,existing){
  const key=payload.request_id||uuid();payload.request_id=key;
  await QStore.put({key,user:state.boot.user.id,path:'/api/reports'+(existing?.id?'/'+existing.id:''),method:existing?.id?'PUT':'POST',payload,created:new Date().toISOString(),error:null});
  await QStore.del('draft:'+state.boot.user.id);
  try{const registration=await navigator.serviceWorker?.getRegistration();if(registration&&'sync' in registration)await registration.sync.register('qaldyq-reports');}catch{/* Online event remains the fallback. */}
  await refreshOfflineStatus();
}

async function syncReports(){
  if(syncBusy||!state.boot||!navigator.onLine)return;
  syncBusy=true;
  try{const result=await QStore.sync();if(result.sent){toast(`${result.sent} есеп серверге жіберілді.`);await loadData();}await refreshOfflineStatus();}catch{/* Retry on reconnection; retain the durable queue. */}finally{syncBusy=false;}
}

async function openQueue(){
  const tasks=(await QStore.tasks()).filter(t=>t.user===state.boot.user.id);
  openDialog(dialogHeading('Жіберу кезегі','Есептер мен фотолар осы құрылғыда сақталады. Жіберілгені расталғанда кезектен өшеді.')+`<div class="detail-body"><p class="data-note">Байланыс қалпына келгенде ашық қосымша автоматты жібереді. Фондық жіберу қолдауы браузерге байланысты. Сессия біткенде өз аккаунтыңызға қайта кіріңіз.</p>${tasks.length?tasks.map(t=>`<article class="queue-row"><strong>${esc(orgName(t.payload.org_id))} · ${esc(t.payload.report_date)}</strong><p>${t.payload.submit?'Тексеруге жіберіледі':'Черновик сақталады'} · ${t.payload.items.length} жол</p>${t.error?`<p class="form-error">${esc(t.error)}</p>`:'<span class="badge draft">Кезекте</span>'}<div><button class="btn secondary small" data-queue-edit="${t.key}">Қарау / түзету</button><button class="text-link" data-queue-remove="${t.key}">Кезектен алып тастау</button></div></article>`).join(''):'<p>Кезекте есеп жоқ.</p>'}</div><div class="dialog-footer"><button class="btn secondary" data-close>Жабу</button><button class="btn primary" id="sync-now">Қазір жіберу</button></div>`,true);
  $('#sync-now').onclick=async()=>{await syncReports();await openQueue();};
  $$('[data-queue-edit]').forEach(b=>b.onclick=()=>{const t=tasks.find(t=>t.key===b.dataset.queueEdit);openReportForm({...t.payload,id:t.method==='PUT'?Number(t.path.split('/').pop()):undefined,_local:true,_queueKey:t.key});});
  $$('[data-queue-remove]').forEach(b=>b.onclick=async()=>{await QStore.remove(b.dataset.queueRemove);await refreshOfflineStatus();openQueue();});
}

function captureForm(existing,photo){
  return {org_id:Number($('#form-org').value),report_date:$('#form-date').value,note:$('#form-note').value,photo,portions:$('#form-portions').value?Number($('#form-portions').value):null,
    items:$$('.waste-row').map(el=>({category_id:Number($('[name="category"]',el).value),kg:Number($('[name="kg"]',el).value),route:$('[name="route"]',el).value,stage:$('[name="stage"]',el)?.value||'other'})),
    dishes:$$('.dish-row').map(el=>({name:$('[name="dish-name"]',el).value.trim(),prepared:Number($('[name="prepared"]',el).value),served:Number($('[name="served"]',el).value),leftover:Number($('[name="leftover"]',el).value),leftover_kg:Number($('[name="leftover_kg"]',el).value)})),submit:$('#save-mode')?.value==='submit',updated_at:existing?.updated_at,id:existing?.id,request_id:existing?.request_id,_queueKey:existing?._queueKey};
}

function foodFormMarkup(existing){
  return `<section class="food-form-section"><div class="form-section-title"><h3>Порция және тағам</h3><span class="pill">Жаңа</span></div><label>Қызмет көрсетілген порция саны<input id="form-portions" type="number" min="1" max="100000" step="1" value="${existing?.portions||''}" placeholder="Мысалы, 250"></label><p class="small muted">Бір ас ішушінің толық порциясын бір рет санаңыз. Көрсеткіш: жалпы қалдық ÷ қызмет көрсетілген порция × 100.</p><div id="dish-rows">${(existing?.dishes||[]).map(dishRow).join('')}</div><button class="text-link" type="button" id="add-dish">${icon('plus')} Тағам қосу</button><p class="small muted">Артылған тағамның кг мәні жоғарыдағы жалпы қалдық массасына кіреді. Екінші рет қосылмайды. Порция мен тағам жолдары — міндетті емес.</p></section>`;
}
function dishRow(d={}){
  return `<div class="dish-row"><label>Тағам атауы<input name="dish-name" value="${esc(d.name||'')}" required minlength="2" maxlength="100" placeholder="Мысалы, палау"></label>${[['prepared','Дайындалды'],['served','Сатылды'],['leftover','Артылды'],['leftover_kg','Артылғаны, кг']].map(([key,label])=>`<label>${label}<input name="${key}" type="number" min="${key==='prepared'?1:0}" max="${key==='leftover_kg'?10000:100000}" step="${key==='leftover_kg'?'0.01':'1'}" value="${d[key]??''}" required></label>`).join('')}<button type="button" class="icon-btn remove-dish" aria-label="Тағам жолын жою">${icon('close')}</button></div>`;
}
function bindFoodForm(existing,getPhoto){
  const userId=state.boot.user.id;
  const bind=()=>$$('.remove-dish').forEach(b=>b.onclick=()=>{b.closest('.dish-row').remove();save();});
  const save=()=>{clearTimeout(localDraftTimer);const payload=captureForm(existing,getPhoto());localDraftTimer=setTimeout(async()=>{try{await QStore.set('draft:'+userId,payload);if(state.boot?.user.id!==userId)return;const el=$('#local-save-note');if(el)el.textContent='Форма осы құрылғыға сақталды.';}catch{if(state.boot?.user.id===userId)toast('Құрылғы жадына сақтау орындалмады. Бос орынды тексеріңіз.',true);}},250);};
  $('#add-dish').onclick=()=>{if($$('.dish-row').length>=30)return;$('#dish-rows').insertAdjacentHTML('beforeend',dishRow());bind();save();};bind();
  $('#report-form').addEventListener('input',save);$('#report-form').addEventListener('change',save);
  return save;
}

function qrLink(org,base){return new URL('/?org='+org+'#new-report',base||location.origin).href;}
function qrMarkup(url){const qr=qrcode(0,'M');qr.addData(url);qr.make();return qr.createSvgTag({cellSize:5,margin:20,scalable:true});}
function telegramQrCard(){
  const url=state.boot.telegram?.url;
  if(!url)return '';
  return `<section class="panel qr-card" id="telegram-qr-card"><span class="eyebrow">Telegram · Qaldyq</span><h2>${esc(QaldyqI18n.language==='ru'?'Бот Qaldyq':'Qaldyq боты')}</h2><div class="qr-image">${qrMarkup(url)}</div><p>Қызметкер: /link → /employee · Студент: /student</p><a class="small qr-url" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a><div class="qr-actions"><a class="btn primary small" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Telegram-да ашу / Открыть</a><button class="btn secondary small" id="telegram-qr-download">SVG жүктеу / Скачать SVG</button></div></section>`;
}
function qrView(){
  const orgs=state.boot.organizations.filter(o=>state.boot.user.role!=='operator'||o.id===state.boot.user.org_id);
  return heading('Асхана QR-кодтары','Кодты телефон камерасымен сканерлеңіз — сол ұйымның есеп формасы ашылады.')+telegramQrCard()+`<section class="panel food-panel"><label>Қызметтің телефоннан ашылатын мекенжайы<input id="qr-base" type="url" value="${esc(location.origin)}" placeholder="https://campus.example.kz"></label><p class="data-note">Қазір жоба осы компьютерде іске қосылған. Телефоннан пайдалану үшін сервердің қолжетімді HTTPS мекенжайын енгізіңіз. 127.0.0.1 телефоныңызда осы компьютерді ашпайды.</p><button class="btn secondary" id="qr-refresh">QR-кодтарды жаңарту</button><p class="form-error" id="qr-error" role="alert"></p></section><div class="qr-grid" id="qr-cards">${qrCards(orgs,location.origin)}</div>`;
}
function qrCards(orgs,base){return orgs.map(o=>{const url=qrLink(o.id,base);return `<article class="panel qr-card"><span class="eyebrow">${esc(o.kind)}</span><h2>${esc(o.name)}</h2><div class="qr-image">${qrMarkup(url)}</div><p>Өлшеңіз. Тіркеңіз. Жіберіңіз.</p><a class="small qr-url" href="${esc(url)}">${esc(url)}</a><div class="qr-actions"><button class="btn primary small" data-qr-open="${o.id}">Форманы ашу</button><button class="btn secondary small" data-qr-download="${o.id}">SVG жүктеу</button></div></article>`;}).join('');}
function bindQrCards(){
  $$('[data-qr-open]').forEach(b=>b.onclick=()=>{if(!canCreate())return toast('Форманы ашу үшін қызметкер немесе әкімші болып кіріңіз.',true);if(state.boot.user.role==='operator'&&state.boot.user.org_id!==Number(b.dataset.qrOpen))return toast('Өз асханаңыздың QR-кодын қолданыңыз.',true);openReportForm({org_id:Number(b.dataset.qrOpen),_local:true});});
  $$('[data-qr-download]').forEach(b=>b.onclick=()=>{const url=b.closest('.qr-card').querySelector('.qr-url').href;const blob=new Blob([qrMarkup(url)],{type:'image/svg+xml'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='qaldyq-qr-'+b.dataset.qrDownload+'.svg';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});
}
function bindQr(){bindQrCards();const botDownload=$('#telegram-qr-download');if(botDownload)botDownload.onclick=()=>{const url=state.boot.telegram?.url;if(!url)return;const blob=new Blob([qrMarkup(url)],{type:'image/svg+xml'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='qaldyq-telegram-qr.svg';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};$('#qr-refresh').onclick=()=>{try{const base=new URL($('#qr-base').value);if(!['http:','https:'].includes(base.protocol)||base.username||base.password)throw Error();$('#qr-cards').innerHTML=qrCards(state.boot.organizations.filter(o=>state.boot.user.role!=='operator'||o.id===state.boot.user.org_id),base.origin);$('#qr-error').textContent='';bindQrCards();}catch{$('#qr-error').textContent='HTTP немесе HTTPS мекенжайын енгізіңіз.';}};}

function foodView(){
  const f=state.food;
  return heading('Ас мәзірі және жоспар','Қай тағам артылады, 100 порцияға қанша қалдық келеді және келесі күні қанша дайындау керек?')+workerBanner('count')+filters()+`<section class="panel food-panel"><div class="food-actions"><label>Жоспарлау күні<input id="planning-date" type="date" value="${state.planningDate||''}"></label><button class="btn primary" id="food-refresh">Талдауды жаңарту</button></div><p class="data-note">Талдау таңдалған кезеңдегі қабылданған есептерден жасалады. Ұсыныс жоспарлау күніне дейінгі соңғы 56 күннен есептеледі; ұйым сүзгісі ескеріледі.</p></section>`+(f?`<div class="food-kpis"><article class="panel"><span>100 порцияға қалдық</span><strong>${f.kg_per_100===null?'—':fmt(f.kg_per_100,2)+' кг'}</strong><p>${fmt(f.covered_kg,2)} кг ÷ ${fmt(f.portions)} порция × 100</p></article><article class="panel"><span>Порция дерегінің қамтылуы</span><strong>${f.covered_reports} / ${f.accepted_reports}</strong><p>Порциясы жазылған / барлық қабылданған есеп. Порциясыз есеп бұл көрсеткішке кірмейді.</p></article></div><section class="panel"><div class="panel-title"><div><h2>Жиі артылатын тағамдар</h2><p>Тағам, ұйым және аптаның күні бойынша</p></div></div><div class="table-scroll"><table><thead><tr><th>ТАҒАМ / ҰЙЫМ</th><th>АПТА КҮНІ</th><th>АРТЫЛҒАН КҮН</th><th>АРТЫЛҒАН ПОРЦИЯ</th><th>КГ</th><th>%</th></tr></thead><tbody>${f.excess.map(r=>`<tr><td><strong>${esc(r.name)}</strong><small class="block-muted">${esc(r.org_name)}</small></td><td>${weekNames[r.weekday]}</td><td>${r.excess_days} / ${r.days}</td><td>${fmt(r.leftover)}</td><td>${fmt(r.kg,2)}</td><td>${fmt(r.leftover_pct,1)}%</td></tr>`).join('')||'<tr><td colspan="6">Тағам туралы қабылданған есеп жоқ. Жаңа есепте «Тағам қосу» батырмасын басыңыз.</td></tr>'}</tbody></table></div></section><section class="panel"><div class="panel-title"><div><h2>${esc(f.target)} күніне дайындау ұсынысы</h2><p>Қызметкер бекітетін бастапқы жоспар</p></div></div><p class="method-note">${esc(f.method)} Мереке, бронь және мәзір өзгерісін жауапты қызметкер ескереді.</p><div class="plan-grid">${f.recommendations.map(r=>`<article class="plan-card"><span class="eyebrow">${esc(r.org_name)}</span><h3>${esc(r.name)}</h3><strong>${r.suggested===null?'Дерек аз':fmt(r.suggested)+' порция'}</strong><p>${r.sample_days} күн · ${r.same_weekday?'аптаның сол күні':'соңғы қолжетімді күндер'}<br>Сатылған медиана: ${fmt(r.median_served,1)}<br>Ауқым: ${r.min_served}–${r.max_served} · Орташа дайындалғаны: ${r.mean_prepared}</p><small>Соңғы дерек: ${r.last_date}${r.suggested===null?' · Кемінде 3 күн толтырыңыз.':''}</small></article>`).join('')||'<p class="method-note">Соңғы 56 күнде тағамның сатылған порциялары жоқ. Ұсыныс үшін кемінде 3 күндік қабылданған есеп қажет.</p>'}</div></section>`:'<section class="panel food-panel">Талдау үшін «Талдауды жаңарту» батырмасын басыңыз.</section>');
}
async function loadFood(){
  const sequence=++foodLoadSequence;
  try{const target=state.planningDate||new Date(Date.now()+86400000).toLocaleDateString('en-CA');state.planningDate=target;const result=await api('/api/food-insights?'+queryString()+'&target='+target);if(sequence!==foodLoadSequence)return;state.food=result;if(state.view==='food')renderMain();}catch(e){toast(e.message,true);}
}
function bindFood(){if(!state.planningDate){const d=new Date();d.setDate(d.getDate()+1);state.planningDate=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;$('#planning-date').value=state.planningDate;}$('#planning-date').onchange=e=>{state.planningDate=e.target.value;};$('#food-refresh').onclick=loadFood;}

async function pollNotifications(){
  if(!state.boot||!navigator.onLine)return;
  const userId=state.boot.user.id;
  try{const data=await api('/api/notifications');if(state.boot?.user.id!==userId)return;state.inbox=data;const unread=data.notifications.filter(n=>!n.read_at&&!n.resolved_at);const bell=$('#notifications');if(bell)bell.setAttribute('aria-label',`Ескерту мен мерзімдер · ${unread.length} оқылмаған`);
    const dot=$('.notification-dot');if(dot)dot.hidden=!unread.length;
    if('Notification' in window&&Notification.permission==='granted')for(const n of unread){const key='notified:'+state.boot.user.id+':'+n.id;if(!await QStore.get(key)){const reg=await navigator.serviceWorker?.getRegistration();if(reg)await reg.showNotification(QaldyqI18n.text(n.title),{body:QaldyqI18n.text(n.message),tag:'qaldyq-'+n.id,icon:'/favicon.svg'});await QStore.set(key,true);}}
    if(state.view==='notifications'){
      const input=$('#deadline-day'),draft=input&&input.value!==input.defaultValue?input.value:null;
      renderMain();
      if(draft!==null&&$('#deadline-day'))$('#deadline-day').value=draft;
    }
  }catch{/* Inbox remains available after reconnect. */}
}
function notificationsView(){
  const inbox=state.inbox||{notifications:[],deadline_day:5};
  return heading('Хабарламалар','Қызметкерге арналған жеке ескертулер және есеп тапсыру мерзімдері.')+`<section class="panel food-panel"><h2>Айлық есеп мерзімі</h2><p>Алдыңғы айдың есебін келесі айдың <strong>${inbox.deadline_day}-іне дейін</strong> жіберіңіз. Сервер минут сайын тексереді; мерзімі келгенде ұйымының есебін жібермеген әр қызметкерге жеке хабарлама жасалады. Черновик пен қайтарылған есеп тапсырылған болып саналмайды.</p><button class="btn secondary" id="enable-browser-notifications">Браузер хабарламаларын қосу</button><p class="small muted">Жеке ескерту осы бөлімде сақталады. Жүйелік хабарлама рұқсат берілгенде және қосымша ашық тұрғанда көрсетіледі.</p>${state.boot.user.role==='admin'?`<form id="deadline-form" class="food-actions"><label>Келесі айдың мерзім күні<input type="number" id="deadline-day" min="1" max="28" step="1" value="${inbox.deadline_day}" required></label><button class="btn primary" type="submit">Мерзімді сақтау</button></form>`:''}</section><section class="panel"><div class="panel-title"><h2>Жеке хабарламалар</h2><button class="btn secondary small" id="inbox-refresh">Жаңарту</button></div><div class="inbox-list">${inbox.notifications.length?inbox.notifications.map(n=>`<article class="inbox-message ${n.read_at?'':'unread'}"><div><h3>${esc(n.title)}</h3><p>${esc(n.message)}</p><small>${localTime(n.created_at)} · ${n.resolved_at?'Есеп жіберілді':n.read_at?'Оқылды':'Жаңа'}</small></div>${!n.read_at?`<button class="btn secondary small" data-read-notification="${n.id}">Оқылды</button>`:''}</article>`).join(''):'<p class="method-note">Сізге хабарлама жоқ. Мерзімі келген ескертулер осында түседі.</p>'}</div></section>`;
}
function bindNotifications(){
  $('#inbox-refresh').onclick=pollNotifications;
  $('#enable-browser-notifications').onclick=async()=>{try{if(!('Notification' in window))throw Error('Браузер бұл хабарлама түрін қолдамайды.');const p=await Notification.requestPermission();toast(p==='granted'?'Браузер хабарламалары қосылды.':'Жеке ескертулер хабарламалар бөлімінде қалады.');if(p==='granted')pollNotifications();}catch(e){toast(e.message,true);}};
  $$('[data-read-notification]').forEach(b=>b.onclick=async()=>{try{await api('/api/notifications/read',{method:'POST',body:{id:Number(b.dataset.readNotification)}});await pollNotifications();}catch(e){toast(e.message,true);}});
  if($('#deadline-form'))$('#deadline-form').onsubmit=async e=>{e.preventDefault();const input=$('#deadline-day'),value=input.value;try{await api('/api/reminder-settings',{method:'POST',body:{deadline_day:Number(value)}});input.defaultValue=value;toast('Есеп мерзімі сақталды.');await pollNotifications();}catch(e){toast(e.message,true);}};
}
