'use strict';
/* Qaldyq student app: public menu, favourites, pre-orders and profile. The same server rules apply
   to this page, the Telegram Mini App and the bot; nothing is reserved until the server confirms. */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const uuid = () => globalThis.crypto?.randomUUID ? crypto.randomUUID() : [...crypto.getRandomValues(new Uint8Array(16))].map((b, i) => ([4, 6, 8, 10].includes(i) ? '-' : '') + b.toString(16).padStart(2, '0')).join('');
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } }, del(k) { try { localStorage.removeItem(k); } catch { /* private mode */ } } };

const T = {
  home: ['Басты', 'Главная'], menu: ['Мәзір', 'Меню'], favorites: ['Таңдаулы', 'Избранное'], orders: ['Тапсырыстар', 'Заказы'], profile: ['Профиль', 'Профиль'],
  hello: ['Сәлем', 'Привет'], hello_guest: ['Қош келдіңіз', 'Добро пожаловать'], home_sub: ['Асхана мәзірін қараңыз және тағамды алдын ала брондаңыз.', 'Смотрите меню столовых и бронируйте блюда заранее.'],
  canteens: ['Асханалар', 'Столовые'], hours: ['Жұмыс уақыты', 'Время работы'], see_menu: ['Мәзірді көру', 'Смотреть меню'],
  no_pay: ['Онлайн төлем жоқ. Тапсырыс — тек бронь; төлем асханада алу кезінде жасалады.', 'Онлайн-оплаты нет. Заказ — только бронь; оплата в столовой при получении.'],
  demo: ['Демо нұсқа: мәзір, бағалар мен мекенжайлар үлгі ретінде берілген.', 'Демо-версия: меню, цены и адреса приведены для примера.'],
  all: ['Барлық асхана', 'Все столовые'], today: ['Бүгін', 'Сегодня'], tomorrow: ['Ертең', 'Завтра'], search: ['Тағам іздеу', 'Поиск блюда'],
  no_menu: ['Бұл күнге мәзір жарияланбаған.', 'На эту дату меню не опубликовано.'], nothing: ['Ештеңе табылмады.', 'Ничего не найдено.'],
  left: ['Қалды', 'Осталось'], sold_out: ['Таусылды', 'Закончилось'], add: ['Қосу', 'Добавить'], grams: ['г', 'г'], composition: ['Құрамы', 'Состав'],
  closed: ['Тапсырыс қабылдау аяқталды', 'Приём заказов завершён'], until: ['Тапсырыс қабылдау', 'Приём заказов до'],
  cached: ['Байланыс жоқ. Мәзір сақталған көшірмеден: {0}. Қолда бар-жоғы өзекті болмауы мүмкін.', 'Нет связи. Меню из сохранённой копии: {0}. Наличие может быть неактуальным.'],
  offline: ['Байланыс жоқ', 'Нет связи'], cart: ['Себет', 'Корзина'], portions: ['порция', 'порц.'], checkout: ['Тапсырысты рәсімдеу', 'Оформить заказ'],
  pickup: ['Алу уақыты', 'Время получения'], slot_free: ['бос орын', 'свободно'], total: ['Барлығы', 'Итого'], confirm: ['Тапсырысты растау', 'Подтвердить заказ'],
  pay_at: ['Төлем: алу кезінде, асханада', 'Оплата: при получении, в столовой'], saved_only: ['Таңдау осы құрылғыда сақталды, бірақ порция брондалған жоқ. Брондау үшін байланыс қажет.', 'Выбор сохранён на этом устройстве, но порции не забронированы. Для брони нужна связь.'],
  need_login: ['Тапсырыс беру үшін жүйеге кіріңіз.', 'Чтобы заказать, войдите в систему.'], login: ['Кіру', 'Войти'], register: ['Тіркелу', 'Регистрация'], email: ['Email', 'Email'], password: ['Құпиясөз', 'Пароль'],
  name: ['Аты-жөні', 'Имя и фамилия'], pass_hint: ['Кемінде 8 таңба', 'Не менее 8 символов'], have_account: ['Аккаунтым бар', 'У меня есть аккаунт'], no_account: ['Аккаунтым жоқ — тіркелу', 'Нет аккаунта — регистрация'],
  reg_note: ['Тіркелу тек студент аккаунтын ашады және университетке тиесілілікті растамайды.', 'Регистрация создаёт только аккаунт студента и не подтверждает принадлежность к университету.'],
  demo_login: ['Демо студент ретінде кіру', 'Войти как демо-студент'], logout: ['Шығу', 'Выйти'], save: ['Сақтау', 'Сохранить'], saved: ['Сақталды.', 'Сохранено.'],
  order_ok: ['Тапсырыс расталды. Кодты асханада көрсетіңіз.', 'Заказ подтверждён. Покажите код в столовой.'], no_orders: ['Әзірге тапсырыс жоқ.', 'Заказов пока нет.'],
  st_confirmed: ['Расталды', 'Подтверждён'], st_issued: ['Берілді', 'Выдан'], st_cancelled: ['Тоқтатылды', 'Отменён'], st_no_show: ['Алынбады', 'Не получен'],
  pay_unpaid: ['Төленбеген — алу кезінде төленеді', 'Не оплачен — оплата при получении'], pay_paid: ['Асханада төленді', 'Оплачен в столовой'],
  code: ['Беру коды', 'Код выдачи'], show_code: ['Асхана қызметкеріне осы кодты немесе QR-ды көрсетіңіз.', 'Покажите этот код или QR сотруднику столовой.'],
  cancel: ['Тапсырыстан бас тарту', 'Отменить заказ'], cancel_until: ['Бас тартуға болады', 'Отменить можно до'], cancelled: ['Тапсырыс тоқтатылды.', 'Заказ отменён.'],
  rate: ['Бағалау', 'Оценить'], rated: ['Бағаңыз', 'Ваша оценка'], leftover: ['Тағам қалды ма? (міндетті емес)', 'Осталась ли еда? (необязательно)'],
  r_none: ['Жоқ, бәрін жедім', 'Нет, съел(а) всё'], r_portion_big: ['Порция үлкен', 'Большая порция'], r_taste: ['Дәмі ұнамады', 'Не понравился вкус'], r_cold: ['Суық болды', 'Было холодным'], r_no_time: ['Уақыт жетпеді', 'Не хватило времени'], r_other: ['Басқа себеп', 'Другая причина'],
  thanks: ['Рақмет! Бағаңыз сақталды.', 'Спасибо! Оценка сохранена.'], no_fav: ['Таңдаулы тағам жоқ. Мәзірден ♥ басыңыз.', 'Избранных блюд нет. Нажмите ♥ в меню.'], fav_login: ['Таңдаулыны сақтау үшін жүйеге кіріңіз.', 'Войдите, чтобы сохранять избранное.'],
  notices: ['Хабарламалар', 'Уведомления'], no_notices: ['Хабарлама жоқ.', 'Уведомлений нет.'], telegram: ['Telegram', 'Telegram'],
  tg_linked: ['Telegram байланысқан.', 'Telegram привязан.'], tg_code: ['Байланыстыру кодын алу', 'Получить код привязки'], tg_hint: ['Кодты Qaldyq ботына жіберіңіз. Код 10 минут жарамды және бір рет қолданылады.', 'Отправьте код боту Qaldyq. Код действует 10 минут и используется один раз.'],
  sub_order: ['Тапсырыс күйі туралы хабарлау', 'Сообщать о статусе заказа'], sub_pickup: ['Алу уақыты туралы еске салу', 'Напоминать о времени получения'],
  staff: ['Қызметкерлерге арналған кіру', 'Вход для сотрудников'], staff_only: ['Бұл аккаунт қызметкерге тиесілі. Жұмыс кеңістігіне өтіңіз.', 'Это служебный аккаунт. Перейдите в рабочее пространство.'],
  net_error: ['Сервермен байланыс жоқ. Кейінірек қайталаңыз.', 'Нет связи с сервером. Повторите позже.'], updated: ['Жаңартылды', 'Обновлено'], install: ['Қосымшаны негізгі экранға орнатуға болады.', 'Приложение можно установить на главный экран.'],
  empty_cart: ['Себет бос.', 'Корзина пуста.'], choose_slot: ['Алу уақытын таңдаңыз.', 'Выберите время получения.'], no_slots: ['Бос уақыт қалмады.', 'Свободного времени не осталось.'], at: ['сағат', 'в'],
};
const state = { lang: store.get('qaldyq-language', 'kk') === 'ru' ? 'ru' : 'kk', tab: 'home', user: null, csrf: '', canteens: [], org: 0, date: '', menus: [], menuTime: '', cached: false, search: '', cart: store.get('qaldyq-cart', {}), favorites: new Set(), orders: null, online: navigator.onLine };
const t = (key, ...args) => (T[key] || [key, key])[state.lang === 'ru' ? 1 : 0].replace(/\{(\d)\}/g, (_, i) => args[i]);
const nm = (obj, key = 'name') => (state.lang === 'ru' && obj[key + '_ru']) || obj[key];
const tenge = tiyn => (tiyn / 100).toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' ₸';
const icons = { home: 'M3 11 12 3l9 8M5 10v10h14V10', menu: 'M4 6h16M4 12h16M4 18h10', favorites: 'M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z', orders: 'M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6', profile: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21a8 8 0 0 1 16 0' };
const isoDay = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const telegramApp = window.Telegram?.WebApp;
const telegramInitData = telegramApp?.initData || '';

async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, { credentials: telegramInitData ? 'omit' : 'same-origin', cache: 'no-store', ...options, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf, ...(telegramInitData ? {Authorization:'tma '+telegramInitData} : {}), ...options.headers }, body: options.body ? JSON.stringify(telegramInitData&&path==='/api/student/orders'&&options.method==='POST'?{...options.body,source:'miniapp'}:options.body) : undefined }); }
  catch { setOnline(false); throw Object.assign(new Error(t('net_error')), { network: true }); }
  setOnline(true);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || t('net_error')), { status: response.status });
  return data;
}
function setOnline(value) { state.online = value; const el = $('#net'); el.hidden = value; el.textContent = t('offline'); }
function toast(message, bad = false) { const el = $('#toast'); el.textContent = message; el.className = 's-toast show' + (bad ? ' bad' : ''); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove('show'), 4200); }
function sheet(html) { $('#sheet-body').innerHTML = html; $('#sheet').hidden = false; $$('[data-x]', $('#sheet')).forEach(b => b.onclick = closeSheet); }
function closeSheet() { $('#sheet').hidden = true; $('#sheet-body').innerHTML = ''; }

/* ---------- session ---------- */
async function loadSession() {
  try {
    const me = await api('/api/me'); state.user = me.user; state.csrf = me.csrf;
    if(telegramInitData&&me.preferences){state.lang=me.preferences.language;state.org=me.preferences.org_id||state.org;}
    if (state.user.role === 'student' || state.user) { const fav = await api('/api/student/favorites'); state.favorites = new Set(fav.dishes.map(d => d.id)); }
  } catch (error) { if (!error.network) { state.user = null; state.csrf = ''; state.favorites = new Set(); } }
}
function authSheet(mode = 'login', after = null) {
  const reg = mode === 'register';
  sheet(`<div class="s-sheet-head"><h2>${t(reg ? 'register' : 'login')}</h2><button class="s-x" data-x aria-label="×">×</button></div><form id="auth">${reg ? `<label for="a-name">${t('name')}</label><input id="a-name" required minlength="2" maxlength="80" autocomplete="name">` : ''}<label for="a-email">${t('email')}</label><input id="a-email" type="email" required autocomplete="username"><label for="a-pass">${t('password')}</label><input id="a-pass" type="password" required minlength="${reg ? 8 : 1}" autocomplete="${reg ? 'new-password' : 'current-password'}" placeholder="${reg ? t('pass_hint') : ''}">${reg ? `<p class="s-note info" style="margin-top:12px">${t('reg_note')}</p>` : ''}<p class="s-err" id="a-err" role="alert"></p><button class="s-btn full" type="submit">${t(reg ? 'register' : 'login')}</button></form><p style="margin:14px 0 6px"><button class="s-link" id="a-swap">${t(reg ? 'have_account' : 'no_account')}</button></p>${reg ? '' : `<p style="margin:6px 0"><button class="s-link" id="a-demo">${t('demo_login')}</button></p>`}`);
  $('#a-swap').onclick = () => authSheet(reg ? 'login' : 'register', after);
  const enter = async body => {
    await api(reg ? '/api/register' : '/api/login', { method: 'POST', body });
    await loadSession(); closeSheet(); state.orders = null; render(); if (after) after();
  };
  if ($('#a-demo')) $('#a-demo').onclick = () => enter({ email: 'student@atu.kz', password: 'demo2026' }).catch(e => { $('#a-err').textContent = e.message; });
  $('#auth').onsubmit = async e => { e.preventDefault(); try { await enter({ email: $('#a-email').value, password: $('#a-pass').value, ...(reg ? { name: $('#a-name').value } : {}) }); } catch (error) { $('#a-err').textContent = error.message; } };
}

/* ---------- menu ---------- */
const menuKey = () => `qaldyq-menu:${state.date}`;
async function loadMenu() {
  try {
    const data = await api(`/api/public/menu?date=${state.date}`);
    state.menus = data.menus; state.menuTime = data.generated_at; state.cached = false;
    store.set(menuKey(), { menus: data.menus, at: data.generated_at });
  } catch (error) {
    const saved = store.get(menuKey(), null);
    if (error.network && saved) { state.menus = saved.menus; state.menuTime = saved.at; state.cached = true; }
    else { state.menus = []; state.cached = false; if (!error.network) toast(error.message, true); }
  }
  pruneCart(); if (state.tab === 'menu' || state.tab === 'home') render();
}
function pruneCart() {
  // The cart is a saved choice only. Lines for menus that are no longer loaded for this date are kept per date.
  const valid = new Set(state.menus.flatMap(m => m.items.map(i => i.id)));
  const cart = state.cart[state.date] || {};
  for (const id of Object.keys(cart)) if (!valid.has(Number(id))) delete cart[id];
  state.cart[state.date] = cart; store.set('qaldyq-cart', state.cart);
}
const cartLines = () => { const cart = state.cart[state.date] || {}; return state.menus.flatMap(m => m.items.filter(i => cart[i.id]).map(i => ({ ...i, qty: cart[i.id], menu: m }))); };
function setQty(itemId, qty) { const cart = state.cart[state.date] ||= {}; if (qty <= 0) delete cart[itemId]; else cart[itemId] = Math.min(5, qty); store.set('qaldyq-cart', state.cart); renderCartBar(); }
function dayChips() {
  const base = new Date(); const names = state.lang === 'ru' ? ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'] : ['жс', 'дс', 'сс', 'ср', 'бс', 'жм', 'сб'];
  return [...Array(7)].map((_, i) => { const d = new Date(base); d.setDate(d.getDate() + i); const iso = isoDay(d); return `<button class="s-chip ${iso === state.date ? 'on' : ''}" data-date="${iso}">${i === 0 ? t('today') : i === 1 ? t('tomorrow') : `${names[d.getDay()]} ${d.getDate()}`}</button>`; }).join('');
}
function dishCards(menus) {
  const term = state.search.trim().toLocaleLowerCase(); let html = '';
  for (const menu of menus) {
    const canteen = state.canteens.find(c => c.id === menu.org_id) || { name: '' };
    const dishes = new Map();
    for (const item of menu.items) { if (term && !`${item.name} ${item.name_ru || ''} ${item.composition} ${item.composition_ru || ''}`.toLocaleLowerCase().includes(term)) continue; (dishes.get(item.dish_id) || dishes.set(item.dish_id, []).get(item.dish_id)).push(item); }
    if (!dishes.size) continue;
    html += `<h2>${esc(nm(canteen))}</h2><p class="s-sub">${menu.accepting ? `${t('until')}: ${esc(menu.order_deadline.replace('T', ' '))}` : t('closed')}</p><div class="s-grid">`;
    for (const [dishId, items] of dishes) {
      const d = items[0], composition = nm(d, 'composition');
      html += `<article class="s-card s-dish">${d.photo ? `<img class="s-photo" src="${esc(d.photo)}" alt="" loading="lazy">` : `<div class="s-photo" aria-hidden="true">${esc(nm(d)[0])}</div>`}<div><div class="s-dish-head"><h3>${esc(nm(d))}</h3><button class="s-heart ${state.favorites.has(dishId) ? 'on' : ''}" data-fav="${dishId}" aria-label="${t('favorites')}" aria-pressed="${state.favorites.has(dishId)}">♥</button></div>${composition ? `<p>${t('composition')}: ${esc(composition)}</p>` : ''}${items.map(i => { const out = !state.cached && i.remaining <= 0; return `<div class="s-portion"><div><strong>${tenge(i.price_tiyn)}</strong> · ${esc(nm(i, 'label'))}, ${i.grams} ${t('grams')}<br><span class="s-left ${out ? 'out' : ''}">${state.cached ? '' : out ? t('sold_out') : `${t('left')}: ${i.remaining}`}</span></div><button class="s-btn small" data-add="${i.id}" ${out || !menu.accepting ? 'disabled' : ''}>${t('add')}</button></div>`; }).join('')}</div></article>`;
    }
    html += '</div>';
  }
  return html;
}
function viewMenu() {
  const menus = state.menus.filter(m => !state.org || m.org_id === state.org), cards = dishCards(menus);
  return `<h1>${t('menu')}</h1><div class="s-chips">${dayChips()}</div><div class="s-chips"><button class="s-chip ${state.org ? '' : 'on'}" data-org="0">${t('all')}</button>${state.canteens.map(c => `<button class="s-chip ${state.org === c.id ? 'on' : ''}" data-org="${c.id}">${esc(nm(c))}</button>`).join('')}</div><input class="s-search" id="search" type="search" placeholder="${t('search')}" value="${esc(state.search)}" aria-label="${t('search')}">${state.cached ? `<p class="s-note">${t('cached', esc(state.menuTime.replace('T', ' ')))}</p>` : ''}<p class="s-note info">${t('no_pay')}</p>${cards || `<p class="s-empty">${menus.length ? t('nothing') : t('no_menu')}</p>`}${!state.cached && state.menuTime ? `<p class="s-sub">${t('updated')}: ${esc(state.menuTime.replace('T', ' '))}</p>` : ''}`;
}
function renderCartBar() {
  const lines = cartLines(), bar = $('#cart-bar'), show = lines.length && ['menu', 'home', 'favorites'].includes(state.tab);
  bar.hidden = !show; if (!show) return;
  bar.innerHTML = `<button id="cart-open"><span>${t('cart')} · ${lines.reduce((s, l) => s + l.qty, 0)} ${t('portions')}</span><span>${tenge(lines.reduce((s, l) => s + l.qty * l.price_tiyn, 0))}</span></button>`;
  $('#cart-open').onclick = openCart;
}
function openCart() {
  const lines = cartLines();
  if (!lines.length) return toast(t('empty_cart'));
  const menusUsed = [...new Set(lines.map(l => l.menu))];
  const blocks = menusUsed.map(menu => {
    const own = lines.filter(l => l.menu === menu), slots = menu.slots.filter(s => s.open && s.free > 0), canteen = state.canteens.find(c => c.id === menu.org_id) || {};
    return `<h3 style="margin:14px 0 4px">${esc(nm(canteen))} · ${esc(menu.day)}</h3>${own.map(l => `<div class="s-row"><div>${esc(nm(l))}<br><span class="s-left">${esc(nm(l, 'label'))} · ${tenge(l.price_tiyn)}</span></div><div class="s-qty"><button data-dec="${l.id}" aria-label="−">−</button><strong>${l.qty}</strong><button data-inc="${l.id}" aria-label="+">+</button></div></div>`).join('')}<label for="slot-${menu.id}">${t('pickup')}</label><select id="slot-${menu.id}" data-slot="${menu.id}">${slots.map(s => `<option value="${s.time}">${s.time} · ${t('slot_free')}: ${s.free}</option>`).join('') || `<option value="">${t('no_slots')}</option>`}</select><div class="s-total"><span>${t('total')}</span><span>${tenge(own.reduce((s, l) => s + l.qty * l.price_tiyn, 0))}</span></div><button class="s-btn full" data-confirm="${menu.id}" ${!state.online || state.cached || !menu.accepting || !slots.length ? 'disabled' : ''}>${t('confirm')}</button>`;
  }).join('');
  sheet(`<div class="s-sheet-head"><h2>${t('checkout')}</h2><button class="s-x" data-x aria-label="×">×</button></div><p class="s-note info">${t('pay_at')}. ${t('no_pay')}</p>${!state.online || state.cached ? `<p class="s-note">${t('saved_only')}</p>` : ''}${blocks}<p class="s-err" id="cart-err" role="alert"></p>`);
  $$('[data-inc]').forEach(b => b.onclick = () => { setQty(b.dataset.inc, (state.cart[state.date][b.dataset.inc] || 0) + 1); openCart(); });
  $$('[data-dec]').forEach(b => b.onclick = () => { setQty(b.dataset.dec, (state.cart[state.date][b.dataset.dec] || 0) - 1); cartLines().length ? openCart() : closeSheet(); });
  $$('[data-confirm]').forEach(b => b.onclick = () => confirmOrder(Number(b.dataset.confirm)));
}
async function confirmOrder(menuId) {
  if (!state.user) return authSheet('login', openCart);
  const slot = $(`[data-slot="${menuId}"]`).value; if (!slot) return void ($('#cart-err').textContent = t('choose_slot'));
  const lines = cartLines().filter(l => l.menu.id === menuId), key = store.get('qaldyq-order-key:' + menuId, null) || uuid();
  store.set('qaldyq-order-key:' + menuId, key); // the same key is reused if the answer is lost, so a retry cannot create a second order
  $$('[data-confirm]').forEach(b => b.disabled = true);
  try {
    await api('/api/student/orders', { method: 'POST', body: { menu_id: menuId, pickup_slot: slot, request_id: key, items: lines.map(l => ({ menu_item_id: l.id, qty: l.qty })) } });
    store.del('qaldyq-order-key:' + menuId); lines.forEach(l => setQty(l.id, 0)); closeSheet(); toast(t('order_ok')); state.orders = null; go('orders'); loadMenu();
  } catch (error) {
    // Only a server answer counts. Without one the order is not shown as booked.
    if (!error.network) store.del('qaldyq-order-key:' + menuId);
    const el = $('#cart-err'); if (el) el.textContent = error.network ? t('saved_only') : error.message; $$('[data-confirm]').forEach(b => b.disabled = false);
    if (!error.network) loadMenu();
  }
}

/* ---------- other tabs ---------- */
function viewHome() {
  const today = state.menus.slice(0, 3).flatMap(m => m.items.slice(0, 2).map(i => ({ ...i, org: state.canteens.find(c => c.id === m.org_id) })));
  return `<h1>${state.user ? `${t('hello')}, <span>${esc(state.user.name.split(' ')[0])}</span>!` : t('hello_guest')}</h1><p class="s-sub">${t('home_sub')}</p><p class="s-note info">${t('no_pay')}</p><h2>${t('canteens')}</h2>${state.canteens.map(c => `<article class="s-card"><h3>${esc(nm(c))}</h3><p>${esc(c.address)}</p>${c.hours ? `<p>${t('hours')}: ${esc(c.hours)}</p>` : ''}<p>${esc(c.description)}</p><p style="margin-top:8px"><button class="s-btn small ghost" data-open-org="${c.id}">${t('see_menu')}</button></p></article>`).join('')}${today.length ? `<h2>${t('today')}</h2>${today.map(i => `<div class="s-row"><div>${esc(nm(i))}<br><span class="s-left">${esc(nm(i.org || {}))}</span></div><strong>${tenge(i.price_tiyn)}</strong></div>`).join('')}` : ''}<p class="s-note" style="margin-top:16px">${t('demo')}</p><p class="s-sub">${t('install')}</p>`;
}
async function loadOrders() { if (!state.user) return; try { state.orders = (await api('/api/student/orders')).orders; } catch (error) { if (!error.network) toast(error.message, true); state.orders ||= []; } if (state.tab === 'orders') render(); }
function qrSvg(value) { try { const qr = qrcode(0, 'M'); qr.addData(value); qr.make(); return qr.createSvgTag({ cellSize: 4, margin: 8, scalable: true }); } catch { return ''; } }
function viewOrders() {
  if (!state.user) return `<h1>${t('orders')}</h1><p class="s-empty">${t('need_login')}</p><button class="s-btn full" data-login>${t('login')}</button>`;
  if (!state.orders) { loadOrders(); return `<h1>${t('orders')}</h1><p class="s-boot">…</p>`; }
  return `<h1>${t('orders')}</h1>${state.orders.map(o => `<article class="s-card"><div class="s-dish-head"><h3>№${o.id} · ${esc(nm(o, 'org_name'))}</h3><span class="s-badge ${o.status}">${t('st_' + o.status)}</span></div><p>${esc(o.day)} ${t('at')} ${esc(o.pickup_slot)} · ${esc(o.org_address || '')}</p>${o.items.map(i => `<div class="s-row"><div>${esc(nm(i))} × ${i.qty}<br><span class="s-left">${esc(i.portion_label)} · ${tenge(i.price_tiyn)}</span></div>${o.status === 'issued' ? (i.rating ? `<span class="s-left">${t('rated')}: ${'★'.repeat(i.rating)}</span>` : `<button class="s-btn small ghost" data-review="${o.id}:${i.id}">${t('rate')}</button>`) : ''}</div>`).join('')}<div class="s-total"><span>${t('total')}</span><span>${tenge(o.total_tiyn)}</span></div><p>${t(o.payment_status === 'paid' ? 'pay_paid' : 'pay_unpaid')}</p>${o.status === 'confirmed' ? `<div class="s-code">${qrSvg(o.qr)}<div><span class="s-left">${t('code')}</span><br><strong>${esc(o.code)}</strong><p>${t('show_code')}</p></div></div>${o.can_cancel ? `<p style="margin-top:10px"><button class="s-btn danger small" data-cancel="${o.id}">${t('cancel')}</button> <span class="s-left">${t('cancel_until')}: ${esc(o.cancel_until.replace('T', ' '))}</span></p>` : ''}` : ''}</article>`).join('') || `<p class="s-empty">${t('no_orders')}</p>`}`;
}
function reviewSheet(orderId, itemId) {
  let rating = 5;
  sheet(`<div class="s-sheet-head"><h2>${t('rate')}</h2><button class="s-x" data-x aria-label="×">×</button></div><div class="s-stars" id="stars">${[1, 2, 3, 4, 5].map(n => `<button data-star="${n}" class="on" aria-label="${n}">★</button>`).join('')}</div><label for="r-reason">${t('leftover')}</label><select id="r-reason">${['none', 'portion_big', 'taste', 'cold', 'no_time', 'other'].map(r => `<option value="${r}">${t('r_' + r)}</option>`).join('')}</select><p class="s-err" id="r-err" role="alert"></p><button class="s-btn full" id="r-save">${t('save')}</button>`);
  $$('[data-star]').forEach(b => b.onclick = () => { rating = Number(b.dataset.star); $$('[data-star]').forEach(x => x.classList.toggle('on', Number(x.dataset.star) <= rating)); });
  $('#r-save').onclick = async () => { try { await api(`/api/student/orders/${orderId}/review`, { method: 'POST', body: { order_item_id: itemId, rating, leftover_reason: $('#r-reason').value } }); closeSheet(); toast(t('thanks')); loadOrders(); } catch (error) { $('#r-err').textContent = error.message; } };
}
function viewFavorites() {
  if (!state.user) return `<h1>${t('favorites')}</h1><p class="s-empty">${t('fav_login')}</p><button class="s-btn full" data-login>${t('login')}</button>`;
  const menus = state.menus.map(m => ({ ...m, items: m.items.filter(i => state.favorites.has(i.dish_id)) })).filter(m => m.items.length);
  return `<h1>${t('favorites')}</h1><div class="s-chips">${dayChips()}</div>${dishCards(menus) || `<p class="s-empty">${state.favorites.size ? t('no_menu') : t('no_fav')}</p>`}`;
}
function viewProfile() {
  if (!state.user) return `<h1>${t('profile')}</h1><p class="s-sub">${t('need_login')}</p><button class="s-btn full" data-login>${t('login')}</button><p style="margin-top:12px"><button class="s-btn ghost full" data-register>${t('register')}</button></p><p style="margin-top:18px"><a class="s-link" href="/">${t('staff')}</a></p>`;
  const p = state.profile;
  return `<h1>${t('profile')}</h1>${state.user.role !== 'student' ? `<p class="s-note">${t('staff_only')} <a class="s-link" href="/">→</a></p>` : ''}<article class="s-card"><label for="p-name">${t('name')}</label><input id="p-name" value="${esc(state.user.name)}" maxlength="80"><p class="s-sub" style="margin-top:8px">${esc(state.user.email)}</p><button class="s-btn small" id="p-save">${t('save')}</button></article><article class="s-card"><h3>${t('telegram')}</h3>${p?.telegram_linked ? `<p>${t('tg_linked')}</p>` : `<p>${t('tg_hint')}</p><p style="margin-top:8px"><button class="s-btn small ghost" id="p-tg">${t('tg_code')}</button> <strong id="p-code" style="letter-spacing:2px"></strong></p>`}<div class="s-switch"><span>${t('sub_order')}</span><input type="checkbox" data-sub="order_status" ${p?.subscriptions?.order_status !== false ? 'checked' : ''}></div><div class="s-switch"><span>${t('sub_pickup')}</span><input type="checkbox" data-sub="pickup_reminder" ${p?.subscriptions?.pickup_reminder !== false ? 'checked' : ''}></div></article><h2>${t('notices')}</h2>${(state.notices || []).slice(0, 10).map(n => `<div class="s-row"><div><strong>${esc(n.title)}</strong><br><span class="s-left">${esc(n.body)}</span></div></div>`).join('') || `<p class="s-sub">${t('no_notices')}</p>`}<p style="margin-top:18px"><button class="s-btn danger full" id="p-logout">${t('logout')}</button></p>`;
}
async function loadProfile() { if (!state.user) return; try { const [p, n] = await Promise.all([api('/api/student/profile'), api('/api/student/notices')]); state.profile = p; state.notices = n.notices; if (state.tab === 'profile') render(); } catch { /* shown without extras */ } }

/* ---------- shell ---------- */
function go(tab) { state.tab = tab; history.replaceState(null, '', '#' + tab); render(); if (tab === 'orders') loadOrders(); if (tab === 'profile') loadProfile(); window.scrollTo(0, 0); }
function render() {
  document.documentElement.lang = state.lang;
  $$('[data-lang]').forEach(b => b.classList.toggle('on', b.dataset.lang === state.lang));
  $('#nav').innerHTML = Object.keys(icons).map(k => `<button data-tab="${k}" class="${state.tab === k ? 'on' : ''}" ${state.tab === k ? 'aria-current="page"' : ''}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[k]}"/></svg><span>${t(k)}</span>${k === 'orders' && state.orders?.some(o => o.status === 'confirmed') ? `<i class="s-dot">${state.orders.filter(o => o.status === 'confirmed').length}</i>` : ''}</button>`).join('');
  $$('[data-tab]').forEach(b => b.onclick = () => go(b.dataset.tab));
  $('#view').innerHTML = { home: viewHome, menu: viewMenu, favorites: viewFavorites, orders: viewOrders, profile: viewProfile }[state.tab]();
  bind(); renderCartBar();
}
function bind() {
  $$('[data-date]').forEach(b => b.onclick = () => { state.date = b.dataset.date; render(); loadMenu(); });
  $$('[data-org]').forEach(b => b.onclick = () => { state.org = Number(b.dataset.org); render(); });
  $$('[data-open-org]').forEach(b => b.onclick = () => { state.org = Number(b.dataset.openOrg); go('menu'); });
  const search = $('#search'); if (search) search.oninput = () => { const pos = search.selectionStart; state.search = search.value; render(); const next = $('#search'); next.focus(); try { next.setSelectionRange(pos, pos); } catch { /* type=search */ } };
  $$('[data-add]').forEach(b => b.onclick = () => { const id = b.dataset.add; setQty(id, ((state.cart[state.date] || {})[id] || 0) + 1); toast(`${t('cart')}: +1`); });
  $$('[data-fav]').forEach(b => b.onclick = async () => {
    if (!state.user) return authSheet('login');
    const id = Number(b.dataset.fav), on = !state.favorites.has(id);
    try { await api('/api/student/favorites', { method: 'POST', body: { dish_id: id, on } }); on ? state.favorites.add(id) : state.favorites.delete(id); render(); } catch (error) { toast(error.message, true); }
  });
  $$('[data-login]').forEach(b => b.onclick = () => authSheet('login')); $$('[data-register]').forEach(b => b.onclick = () => authSheet('register'));
  $$('[data-cancel]').forEach(b => b.onclick = async () => { b.disabled = true; try { await api(`/api/student/orders/${b.dataset.cancel}/cancel`, { method: 'POST', body: {} }); toast(t('cancelled')); await loadOrders(); loadMenu(); } catch (error) { toast(error.message, true); b.disabled = false; } });
  $$('[data-review]').forEach(b => b.onclick = () => { const [order, item] = b.dataset.review.split(':').map(Number); reviewSheet(order, item); });
  if ($('#p-save')) $('#p-save').onclick = async () => { try { await api('/api/student/profile', { method: 'PUT', body: { name: $('#p-name').value } }); state.user.name = $('#p-name').value.trim(); toast(t('saved')); } catch (error) { toast(error.message, true); } };
  $$('[data-sub]').forEach(box => box.onchange = async () => { try { await api('/api/student/profile', { method: 'PUT', body: { subscriptions: { [box.dataset.sub]: box.checked } } }); toast(t('saved')); } catch (error) { toast(error.message, true); box.checked = !box.checked; } });
  if ($('#p-tg')) $('#p-tg').onclick = async () => { try { $('#p-code').textContent = (await api('/api/student/telegram-link', { method: 'POST', body: {} })).code; } catch (error) { toast(error.message, true); } };
  if ($('#p-logout')) $('#p-logout').onclick = async () => {
    try { await api('/api/logout', { method: 'POST', body: {} }); } catch { /* the local copy is cleared either way */ }
    // Personal data of this account must not stay on a shared phone.
    state.user = null; state.csrf = ''; state.orders = null; state.profile = null; state.notices = null; state.favorites = new Set(); state.cart = {}; store.del('qaldyq-cart');
    Object.keys(localStorage).filter(k => k.startsWith('qaldyq-order-key:')).forEach(k => store.del(k)); go('home');
  };
}
async function start() {
  telegramApp?.ready(); telegramApp?.expand();
  state.date = isoDay(new Date());
  const tab = location.hash.slice(1); if (icons[tab]) state.tab = tab;
  $$('[data-lang]').forEach(b => b.onclick = () => { state.lang = b.dataset.lang; store.set('qaldyq-language', state.lang); render(); });
  $('#sheet').addEventListener('click', e => { if (e.target === $('#sheet')) closeSheet(); });
  addEventListener('online', () => { setOnline(true); loadMenu(); }); addEventListener('offline', () => setOnline(false));
  setOnline(navigator.onLine);
  try { state.canteens = (await api('/api/public/canteens')).canteens; store.set('qaldyq-canteens', state.canteens); } catch { state.canteens = store.get('qaldyq-canteens', []); }
  await loadSession(); render(); await loadMenu();
  if (state.tab === 'orders') loadOrders(); if (state.tab === 'profile') loadProfile();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}
start();
