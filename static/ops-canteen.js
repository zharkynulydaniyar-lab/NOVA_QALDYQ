'use strict';
/* Canteen staff views: dish catalogue, menu publishing, pre-orders and hand-over by code. */
const canteen = { dishes: null, menu: undefined, day: '', orders: null, reviews: null };
const tenge = tiyn => fmt(tiyn / 100, 2) + ' ₸';
const canteenOrg = () => state.boot.user.org_id || Number(state.org);
const canteenRoles = ['operator', 'admin'];
const orderStatusNames = { confirmed: 'Расталды', issued: 'Берілді', cancelled: 'Тоқтатылды', no_show: 'Алынбады' };
const needOrg = title => heading(title, '') + filters() + '<section class="panel food-panel">Алдымен сүзгіден асхананы таңдаңыз.</section>';
const canteenDay = () => canteen.day || (canteen.day = state.boot.today);

async function loadCatalog() { await guarded(async () => { canteen.dishes = (await api('/api/catalog?org=' + (canteenOrg() || 0))).dishes; if (['catalog', 'menuplan'].includes(state.view)) renderMain(); }); }
QaldyqViews.catalog = {
  label: 'Тағам каталогы', icon: 'book', roles: canteenRoles, load: loadCatalog, reload: true,
  render() {
    return heading('Тағам каталогы', 'Тұрақты тағамдар тізімі. Мәзір осы каталогтан жасалады; есептердегі тарихи тағам жолдары өзгермейді.', `<button class="btn primary" id="dish-add">${icon('plus')} Тағам қосу</button>`) + (state.boot.user.role === 'admin' ? filters() : '') +
      `<section class="panel"><div class="table-scroll"><table><thead><tr><th>ТАҒАМ</th><th>ҰЙЫМ</th><th>ПОРЦИЯ ЖӘНЕ БАҒА</th><th>КҮЙІ</th><th></th></tr></thead><tbody>${(canteen.dishes || []).map(d => `<tr><td><strong>${esc(d.name)}</strong><small class="block-muted">${esc(d.composition)}</small></td><td>${esc(orgName(d.org_id))}</td><td>${d.portions.filter(p => p.active).map(p => `${esc(p.label)} · ${p.grams} г · ${tenge(p.price_tiyn)}`).join('<br>')}</td><td><span class="badge ${d.active ? 'accepted' : 'returned'}"><i></i>${d.active ? 'Белсенді' : 'Өшірілген'}</span></td><td><button class="btn secondary small" data-dish="${d.id}">Өзгерту</button></td></tr>`).join('') || '<tr><td colspan="5">Каталог бос. Алғашқы тағамды қосыңыз.</td></tr>'}</tbody></table></div></section>`;
  },
  bind() { $('#dish-add').onclick = () => openDish(); $$('[data-dish]').forEach(b => b.onclick = () => openDish(canteen.dishes.find(d => d.id === Number(b.dataset.dish)))); },
};
function openDish(d = null) {
  const org = d?.org_id || canteenOrg();
  if (!org) return toast('Алдымен сүзгіден асхананы таңдаңыз.', true);
  const row = (p = {}) => `<div class="dish-row portion-row" data-portion="${p.id || ''}"><label>Порция атауы<input name="label" value="${esc(p.label || '')}" required maxlength="40" placeholder="Толық"></label><label>Орысша<input name="label_ru" value="${esc(p.label_ru || '')}" maxlength="40"></label><label>Салмағы, г<input name="grams" type="number" inputmode="numeric" min="1" max="5000" step="1" value="${p.grams || ''}" required></label><label>Бағасы, ₸<input name="price" type="number" inputmode="decimal" min="0" step="0.01" value="${p.price_tiyn != null ? p.price_tiyn / 100 : ''}" required></label><button type="button" class="icon-btn remove-portion" aria-label="Порцияны алып тастау">${icon('close')}</button></div>`;
  let photo = d?.photo || null;
  dictionaryFormLike(d ? 'Тағамды өзгерту' : 'Тағам қосу', `<p class="small muted">${esc(orgName(org))}</p>${field('dish-name', 'Тағам атауы', d?.name, 'required minlength="2" maxlength="100"')}${field('dish-name-ru', 'Орысша атауы', d?.name_ru, 'maxlength="100"')}${field('dish-composition', 'Құрамы', d?.composition, 'maxlength="400"')}${field('dish-composition-ru', 'Орысша құрамы', d?.composition_ru, 'maxlength="400"')}<div class="form-section-title"><h3>Порция нұсқалары</h3></div><div id="portion-rows">${(d?.portions.filter(p => p.active) || [{}]).map(row).join('')}</div><button class="text-link" type="button" id="portion-add">${icon('plus')} Порция нұсқасын қосу</button><label class="photo-upload" for="dish-photo">${icon('camera')}<div><strong>Тағам фотосы</strong><span>JPEG, PNG, WebP · 400 КБ-қа дейін · міндетті емес</span></div><input id="dish-photo" type="file" accept="image/jpeg,image/png,image/webp"></label><p class="small muted" id="dish-photo-note">${photo ? 'Фото тіркелген' : ''}</p>${d ? checkbox('dish-active', 'Белсенді (мәзірге қосуға болады)', d.active) : ''}`,
    () => api(d ? '/api/catalog/' + d.id : '/api/catalog', { method: d ? 'PUT' : 'POST', body: { org_id: org, name: $('#dish-name').value, name_ru: $('#dish-name-ru').value, composition: $('#dish-composition').value, composition_ru: $('#dish-composition-ru').value, photo, active: d ? $('#dish-active').checked : true, portions: $$('.portion-row').map(el => ({ id: Number(el.dataset.portion) || undefined, label: $('[name=label]', el).value, label_ru: $('[name=label_ru]', el).value, grams: $('[name=grams]', el).value, price: $('[name=price]', el).value })) } }), loadCatalog);
  const bindRows = () => $$('.remove-portion').forEach(b => b.onclick = () => { if ($$('.portion-row').length > 1) b.closest('.portion-row').remove(); });
  bindRows(); $('#portion-add').onclick = () => { if ($$('.portion-row').length < 6) { $('#portion-rows').insertAdjacentHTML('beforeend', row()); bindRows(); QaldyqI18n.apply($('#portion-rows')); } };
  $('#dish-photo').onchange = e => { const file = e.target.files[0]; if (!file) return; if (file.size > 400000) { e.target.value = ''; return toast('Фото 400 КБ-тан аспасын.', true); } const reader = new FileReader(); reader.onload = () => { photo = reader.result; $('#dish-photo-note').textContent = 'Фото тіркелген'; }; reader.readAsDataURL(file); };
}
function dictionaryFormLike(title, body, save, after) {
  openDialog(dialogHeading(title) + `<form id="dict-form"><div class="detail-body">${body}<p class="form-error" id="dict-error" role="alert"></p></div><div class="dialog-footer"><button type="button" class="btn secondary" data-close>Бас тарту</button><button class="btn primary" type="submit">Сақтау</button></div></form>`, true);
  $('#dict-form').onsubmit = async e => { e.preventDefault(); try { await save(); $('#dialog').close(); toast('Сақталды.'); await after(); } catch (error) { $('#dict-error').textContent = error.message; } };
}

/* ---------- menu for a date ---------- */
async function loadMenuPlan() {
  const org = canteenOrg(); if (!org) { canteen.menu = undefined; return; }
  await guarded(async () => { const [menu, dishes] = await Promise.all([api(`/api/menu?org=${org}&date=${canteenDay()}`), api('/api/catalog?org=' + org)]); canteen.menu = menu.menu; canteen.dishes = dishes.dishes; if (state.view === 'menuplan') renderMain(); });
}
QaldyqViews.menuplan = {
  label: 'Мәзірді жариялау', icon: 'leaf', roles: canteenRoles, load: loadMenuPlan, reload: true,
  render() {
    if (!canteenOrg()) return needOrg('Мәзірді жариялау');
    const m = canteen.menu, day = canteenDay(), byPortion = new Map((m?.items || []).map(i => [i.portion_id, i]));
    const portions = (canteen.dishes || []).filter(d => d.active).flatMap(d => d.portions.filter(p => p.active).map(p => ({ ...p, dish: d.name })));
    return heading('Мәзірді жариялау', 'Күнді таңдап, тағамдар мен порция шегін көрсетіңіз. Жарияланған мәзірді студенттер бірден көреді.') + (state.boot.user.role === 'admin' ? filters() : '') +
      `<section class="panel food-panel"><div class="food-actions"><label>Мәзір күні<input type="date" id="menu-day" value="${esc(day)}" min="${esc(state.boot.today)}"></label><span class="badge ${m?.status === 'published' ? 'accepted' : 'draft'}"><i></i>${m ? (m.status === 'published' ? 'Жарияланған' : 'Жарияланбаған') : 'Мәзір жоқ'}</span></div><div class="form-grid menu-settings"><label>Тапсырыс қабылдау аяқталады<input type="datetime-local" id="menu-deadline" value="${esc(m?.order_deadline || day + 'T13:30')}"></label><label>Беру басталады<input type="time" id="menu-start" value="${esc(m?.pickup_start || '11:30')}"></label><label>Беру аяқталады<input type="time" id="menu-end" value="${esc(m?.pickup_end || '14:30')}"></label><label>Аралық, мин<input type="number" id="menu-slot" min="5" max="240" step="5" value="${m?.slot_minutes || 30}"></label><label>Бір аралықтағы тапсырыс шегі<input type="number" id="menu-limit" min="1" max="1000" value="${m?.slot_limit || 25}"></label><label>Бас тартуға дейінгі уақыт, мин<input type="number" id="menu-cancel" min="0" max="1440" value="${m?.cancel_minutes ?? 30}"></label></div></section>` +
      `<section class="panel"><div class="panel-title"><div><h2>Тағамдар және порция шегі</h2><p>Шек — алдын ала тапсырысқа ашылған порция саны. Брондалған саннан төмен түсіруге болмайды.</p></div></div><div class="table-scroll"><table><thead><tr><th>МӘЗІРДЕ</th><th>ТАҒАМ</th><th>ПОРЦИЯ</th><th class="numeric">БАҒАСЫ</th><th class="numeric">ПОРЦИЯ ШЕГІ</th><th class="numeric">БРОНДАЛҒАН</th></tr></thead><tbody>${portions.map(p => { const item = byPortion.get(p.id); return `<tr data-menu-portion="${p.id}"><td><input type="checkbox" name="on" ${item ? 'checked' : ''} aria-label="Мәзірге қосу"></td><td>${esc(p.dish)}</td><td>${esc(p.label)} · ${p.grams} г</td><td class="numeric nowrap">${tenge(p.price_tiyn)}</td><td class="numeric"><input type="number" name="available" min="0" max="5000" step="1" value="${item ? item.available : 20}" class="narrow-input" aria-label="Порция шегі"></td><td class="numeric">${item ? item.reserved : 0}</td></tr>`; }).join('') || '<tr><td colspan="6">Каталогта белсенді тағам жоқ. Алдымен «Тағам каталогы» бөлімінде тағам қосыңыз.</td></tr>'}</tbody></table></div><p class="form-error" id="menu-error" role="alert"></p><div class="food-actions"><button class="btn secondary" id="menu-save">Сақтау</button><button class="btn primary" id="menu-publish">${m?.status === 'published' ? 'Сақтау және жарияланған күйде қалдыру' : 'Сақтау және жариялау'}</button>${m?.status === 'published' ? '<button class="btn danger" id="menu-hide">Жариялаудан алу</button>' : ''}</div><p class="data-note">Онлайн төлем қосылмаған: студент тағамды брондайды, төлем асханада алу кезінде жасалады.</p></section>`;
  },
  bind() {
    if (!canteenOrg()) return;
    $('#menu-day').onchange = e => { canteen.day = e.target.value; loadMenuPlan(); };
    const save = async publish => {
      const body = { org_id: canteenOrg(), day: canteenDay(), order_deadline: $('#menu-deadline').value, pickup_start: $('#menu-start').value, pickup_end: $('#menu-end').value, slot_minutes: $('#menu-slot').value, slot_limit: $('#menu-limit').value, cancel_minutes: $('#menu-cancel').value, items: $$('[data-menu-portion]').filter(r => $('[name=on]', r).checked).map(r => ({ portion_id: Number(r.dataset.menuPortion), available: $('[name=available]', r).value })) };
      try { const result = await api('/api/menu', { method: 'PUT', body }); if (publish !== null) await api(`/api/menu/${result.id}/publish`, { method: 'POST', body: { publish } }); toast(publish ? 'Мәзір жарияланды.' : publish === false ? 'Мәзір жариялаудан алынды.' : 'Мәзір сақталды.'); await loadMenuPlan(); }
      catch (error) { $('#menu-error').textContent = error.message; }
    };
    $('#menu-save').onclick = () => save(null); $('#menu-publish').onclick = () => save(true);
    if ($('#menu-hide')) $('#menu-hide').onclick = () => save(false);
  },
};

/* ---------- pre-orders and hand-over ---------- */
async function loadOrdersBoard() {
  const org = canteenOrg(); if (!org) { canteen.orders = null; return; }
  await guarded(async () => { const [orders, reviews] = await Promise.all([api(`/api/orders?org=${org}&date=${canteenDay()}`), api('/api/orders/reviews?org=' + org)]); canteen.orders = orders; canteen.reviews = reviews; if (state.view === 'orders') renderMain(); });
}
QaldyqViews.orders = {
  label: 'Алдын ала тапсырыстар', icon: 'check', roles: ['operator', 'admin', 'manager'], load: loadOrdersBoard, reload: true,
  render() {
    if (!canteenOrg()) return needOrg('Алдын ала тапсырыстар');
    const o = canteen.orders, staff = canCreate();
    return heading('Алдын ала тапсырыстар', 'Студенттердің броньдары. Тағам студент көрсеткен код бойынша бір рет беріледі; сатылым сол сәтте тіркеледі.') + (state.boot.user.role !== 'operator' ? filters() : '') +
      `<section class="panel food-panel"><div class="food-actions"><label>Күні<input type="date" id="orders-day" value="${esc(canteenDay())}"></label>${staff ? `<label>Беру коды немесе QR мәтіні<input id="issue-code" maxlength="20" autocomplete="off" placeholder="A1B2C3D4" class="code-input"></label><label>Төлем тәсілі<select id="issue-pay"><option value="">Белгіленбеген</option><option value="cash">Қолма-қол</option><option value="card">Карта</option><option value="other">Басқа</option></select></label>${checkbox('issue-paid', 'Төлем алынды', false)}<button class="btn primary" id="issue-go">${icon('check')} Тағамды беру</button>` : ''}</div><p class="form-error" id="issue-error" role="alert"></p><p class="data-note">Бронь — төлем емес. Төлем тәсілі мен күйі беру кезінде бөлек белгіленеді.</p></section>` +
      (o ? `<div class="food-kpis"><article class="panel"><span>Тағамдар бойынша (порция)</span>${o.by_dish.map(d => `<p><strong>${esc(d.name)}</strong> · ${esc(d.portion)}: күтілуде ${d.confirmed}, берілді ${d.issued}, тоқтатылды ${d.cancelled}, алынбады ${d.no_show}</p>`).join('') || '<p>Тапсырыс жоқ.</p>'}</article><article class="panel"><span>Алу уақыты бойынша</span>${o.by_slot.map(s => `<p><strong>${esc(s.slot)}</strong> — ${s.portions} порция</p>`).join('') || '<p>Тапсырыс жоқ.</p>'}</article></div><section class="panel"><div class="table-scroll"><table><thead><tr><th>№</th><th>СТУДЕНТ</th><th>УАҚЫТЫ</th><th>ТАҒАМДАР</th><th class="numeric">СОМА</th><th>КҮЙІ</th><th>ТӨЛЕМ</th><th></th></tr></thead><tbody>${o.orders.map(x => `<tr><td>${x.id}</td><td data-i18n-skip>${esc(x.student)}</td><td>${esc(x.pickup_slot)}</td><td>${x.items.map(i => `${esc(i.name)} (${esc(i.portion_label)}) × ${i.qty}`).join('<br>')}</td><td class="numeric nowrap">${tenge(x.total_tiyn)}</td><td><span class="badge order-${x.status}"><i></i>${orderStatusNames[x.status]}</span></td><td>${x.payment_status === 'paid' ? 'Төленді' : 'Төленбеген'}</td><td class="nowrap">${staff && x.status === 'confirmed' ? `<button class="btn secondary small" data-noshow="${x.id}">Келмеді</button> <button class="text-link" data-order-cancel="${x.id}">Тоқтату</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="8">Бұл күнге тапсырыс жоқ.</td></tr>'}</tbody></table></div></section>` : '<section class="panel food-panel">Жүктелуде…</section>') +
      (canteen.reviews?.dishes.length ? `<section class="panel"><div class="panel-title"><div><h2>Студенттердің бағалары</h2><p>Жиынтық түрде; жеке студент көрсетілмейді</p></div></div><div class="table-scroll"><table><thead><tr><th>ТАҒАМ</th><th class="numeric">БАҒА САНЫ</th><th class="numeric">ОРТАША БАҒА</th><th class="numeric">ТАҒАМ ҚАЛҒАН ЖАУАП</th></tr></thead><tbody>${canteen.reviews.dishes.map(r => `<tr><td>${esc(r.name)}</td><td class="numeric">${r.reviews}</td><td class="numeric">${fmt(r.rating, 2)}</td><td class="numeric">${r.leftovers}</td></tr>`).join('')}</tbody></table></div></section>` : '');
  },
  bind() {
    if (!canteenOrg()) return;
    $('#orders-day').onchange = e => { canteen.day = e.target.value; loadOrdersBoard(); };
    const go = $('#issue-go'); if (go) go.onclick = async () => {
      $('#issue-error').textContent = '';
      try { const result = await api('/api/orders/issue', { method: 'POST', body: { code: $('#issue-code').value, payment_method: $('#issue-pay').value, paid: $('#issue-paid').checked } }); toast(`№${result.order.id} тапсырыс берілді.`); await loadOrdersBoard(); }
      catch (error) { $('#issue-error').textContent = error.message; }
    };
    if ($('#issue-code')) $('#issue-code').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); go.click(); } };
    $$('[data-noshow]').forEach(b => b.onclick = () => guarded(async () => { await api(`/api/orders/${b.dataset.noshow}/no-show`, { method: 'POST', body: {} }); await loadOrdersBoard(); }));
    $$('[data-order-cancel]').forEach(b => b.onclick = () => guarded(async () => { await api(`/api/orders/${b.dataset.orderCancel}/cancel`, { method: 'POST', body: {} }); toast('Тапсырыс тоқтатылды.'); await loadOrdersBoard(); }));
  },
};
