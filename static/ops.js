'use strict';
/* Staff views added on top of app.js: period reports, registry, users, dictionaries, quick entry, account switch.
   Each view registers itself in QaldyqViews; app.js builds the menu and routes from it. */
const QaldyqViews = window.QaldyqViews = {};
const ops = { periods: null, overview: null, month: '', registry: null, filters: { route: '', unit: '' }, users: null };
const stageNames = { prep: 'Дайындау', unsold: 'Сатылмаған тағам', plate: 'Тәрелке қалдығы', storage: 'Сақтаудағы бұзылу', other: 'Басқа' };
const roleLabels = { operator: 'Жауапты қызметкер', reviewer: 'Тексеруші', manager: 'Басшылық', admin: 'Әкімші', student: 'Студент' };
const isAdmin = () => state.boot.user.role === 'admin';
const canEditDictionary = () => isAdmin() || canReview();
const qtyUnit = (value, unit) => `${fmt(value, 2)} ${unitNames[unit] || unit}`;
const exportUrl = extra => '/api/export?' + new URLSearchParams({ start: state.start, end: state.end, org: state.org, category: state.category, route: ops.filters.route, unit: ops.filters.unit, lang: QaldyqI18n.language, ...extra });
async function guarded(action) { try { return await action(); } catch (error) { toast(error.message, true); } }
function field(id, label, value = '', attrs = '') { return `<label>${label}<input id="${id}" value="${esc(value ?? '')}" ${attrs}></label>`; }
function checkbox(id, label, checked) { return `<label class="check-line"><input type="checkbox" id="${id}" ${checked ? 'checked' : ''}> <span>${label}</span></label>`; }
function unitTotals(rows) { return rows.length ? rows.map(t => `<strong>${qtyUnit(t.quantity, t.unit)}</strong>`).join(' · ') : '<span class="muted">Дерек жоқ</span>'; }

/* ---------- Period reports (ТТ 6) ---------- */
async function loadPeriods() {
  const month = ops.month || state.boot.today.slice(0, 7); ops.month = month;
  const [year, m] = month.split('-').map(Number), last = new Date(Date.UTC(year, m, 0)).getUTCDate();
  await guarded(async () => {
    const [list, overview] = await Promise.all([api('/api/periods?org=' + state.org), api(`/api/periods/overview?start=${month}-01&end=${month}-${String(last).padStart(2, '0')}`)]);
    ops.periods = list.periods; ops.overview = overview; if (state.view === 'periods') renderMain();
  });
}
QaldyqViews.periods = {
  label: 'Кезең есептері', icon: 'clock', roles: ['operator', 'reviewer', 'manager', 'admin'], load: loadPeriods,
  render() {
    const o = ops.overview, names = list => list.length ? list.map(x => esc(x.name) + (x.status ? ` <span class="muted">(${statusNames[x.status]})</span>` : '')).join('<br>') : '<span class="muted">Жоқ</span>';
    return heading('Кезең есептері', 'Ай ішіндегі өлшемдер бір есеп болып тексеруге жіберіледі. Қабылданған есептің өлшемдері бұғатталады.', canCreate() ? `<button class="btn primary" id="period-open">${icon('plus')} Ай есебін ашу</button>` : '') +
      `<section class="panel food-panel"><div class="food-actions"><label>Ай<input type="month" id="period-month" value="${esc(ops.month)}"></label></div>${o ? `<div class="triple-grid"><div><span class="tiny-label">ЕСЕП ЖІБЕРМЕГЕН</span><p>${names(o.not_submitted)}</p></div><div><span class="tiny-label">ЖІБЕРІЛГЕН, БІРАҚ ҚАБЫЛДАНБАҒАН</span><p>${names(o.not_accepted)}</p></div><div><span class="tiny-label">ҚАБЫЛДАНҒАН</span><p>${names(o.accepted)}</p></div></div>` : '<p class="muted">Жүктелуде…</p>'}</section>` +
      `<section class="panel"><div class="panel-title"><div><h2>Барлық кезең есептері</h2><p>Черновик → жіберілді → тексерілуде → қабылданды немесе қайтарылды</p></div></div><div class="table-scroll"><table><thead><tr><th>ҰЙЫМ</th><th>КЕЗЕҢ</th><th class="numeric">ЖАЗБА</th><th>МӘРТЕБЕ</th><th>ЖІБЕРІЛГЕН УАҚЫТЫ</th><th></th></tr></thead><tbody>${(ops.periods || []).map(p => `<tr><td>${esc(p.org_name)}</td><td class="nowrap">${esc(p.period_start)} – ${esc(p.period_end)}</td><td class="numeric">${p.records}</td><td>${badge(p.status)}</td><td class="nowrap">${p.submitted_at ? localTime(p.submitted_at) : '—'}</td><td><button class="btn secondary small" data-period="${p.id}">Ашу</button></td></tr>`).join('') || '<tr><td colspan="6">Кезең есебі жоқ.</td></tr>'}</tbody></table></div></section>`;
  },
  bind() {
    $('#period-month').onchange = e => { ops.month = e.target.value; loadPeriods(); };
    $$('[data-period]').forEach(b => b.onclick = () => openPeriod(Number(b.dataset.period)));
    const open = $('#period-open'); if (open) open.onclick = () => guarded(async () => {
      const org = state.boot.user.org_id || Number(state.org);
      if (!org) return toast('Алдымен сүзгіден ұйымды таңдаңыз.', true);
      const result = await api('/api/periods', { method: 'POST', body: { org_id: org, month: ops.month } });
      await loadPeriods(); openPeriod(result.id);
    });
  },
};
async function openPeriod(id) {
  await guarded(async () => {
    const p = await api('/api/periods/' + id), mine = canCreate() && ['draft', 'returned'].includes(p.status);
    const counts = Object.entries(p.record_statuses).map(([s, n]) => `${statusNames[s]}: ${n}`).join(' · ') || 'Өлшем жоқ';
    const shown = p.measurements.slice(0, 150);
    openDialog(dialogHeading(`${esc(p.org_name)}`, `${esc(p.period_start)} – ${esc(p.period_end)}`) + `<div class="detail-body"><div class="detail-summary">${badge(p.status)}<span>${unitTotals(p.summary.totals)}</span><span>${esc(counts)}</span></div>${p.reviewer ? `<p class="small muted">Тексеруші: <strong data-i18n-skip>${esc(p.reviewer)}</strong>${p.decided_at ? ' · Шешім уақыты: ' + localTime(p.decided_at) : ''}</p>` : ''}<h3 class="history-title">Қалдық түрлері бойынша жиынтық</h3><div class="table-scroll"><table><thead><tr><th>ҚАЛДЫҚ ТҮРІ</th><th class="numeric">САНЫ</th><th class="numeric">ЖАЗБА</th></tr></thead><tbody>${p.summary.by_type.map(t => `<tr><td>${esc(t.a)}</td><td class="numeric nowrap">${qtyUnit(t.quantity, t.unit)}</td><td class="numeric">${t.records}</td></tr>`).join('') || '<tr><td colspan="3">Өлшем жоқ.</td></tr>'}</tbody></table></div><details class="chart-data-table"><summary>Өлшемдер тізімі · ${p.measurements.length}</summary><div class="table-scroll"><table><thead><tr><th>КҮНІ</th><th>ҚАЛДЫҚ ТҮРІ</th><th class="numeric">САНЫ</th><th>КӘДЕГЕ ЖАРАТУ ТӘСІЛІ</th><th>МӘРТЕБЕ</th></tr></thead><tbody>${shown.map(m => `<tr><td class="nowrap">${esc(m.date)}</td><td>${esc(m.waste)}</td><td class="numeric nowrap">${qtyUnit(m.quantity, m.unit)}</td><td>${esc(m.route_name || m.route)}</td><td>${badge(m.status)}</td></tr>`).join('')}</tbody></table></div>${p.measurements.length > shown.length ? '<p class="small muted">Алғашқы 150 жол көрсетілді. Толық тізім экспортта.</p>' : ''}</details><h3 class="history-title">Өзгерістер тарихы</h3><ol class="history">${p.history.map(h => `<li><span class="history-dot"></span><div><strong>${h.from_status ? esc(statusNames[h.from_status]) + ' → ' : ''}${esc(statusNames[h.to_status])}</strong><span><span data-i18n-skip>${esc(h.name)}</span> · ${localTime(h.created_at)}</span>${h.comment ? `<p>${esc(h.comment)}</p>` : ''}</div></li>`).join('')}</ol>${canReview() && p.status === 'in_review' ? '<label for="period-comment">Тексеруші пікірі <span class="muted">(қайтарғанда міндетті)</span></label><textarea id="period-comment" rows="3" maxlength="2000"></textarea>' : ''}<p class="form-error" id="period-error" role="alert"></p></div><div class="dialog-footer"><button class="btn secondary" data-close>Жабу</button><div>${mine ? '<button class="btn primary" data-move="submitted">Кезең есебін тексеруге жіберу</button>' : ''}${canReview() && p.status === 'submitted' ? '<button class="btn primary" data-move="in_review">Тексеруге алу</button>' : ''}${canReview() && p.status === 'in_review' ? '<button class="btn danger" data-move="returned">Қайтару</button><button class="btn primary" data-move="accepted">Қабылдау</button>' : ''}</div></div>`, true);
    $$('[data-move]').forEach(b => b.onclick = async () => {
      const buttons = $$('[data-move]'); buttons.forEach(x => x.disabled = true);
      try { await api(`/api/periods/${id}/transition`, { method: 'POST', body: { status: b.dataset.move, comment: $('#period-comment')?.value || '', updated_at: p.updated_at } }); toast('Кезең есебінің мәртебесі жаңартылды.'); await Promise.all([loadPeriods(), loadData()]); await openPeriod(id); }
      catch (error) { $('#period-error').textContent = error.message; buttons.forEach(x => x.disabled = false); }
    });
  });
}

/* ---------- Unified registry (ТТ 7) ---------- */
async function loadRegistry() {
  await guarded(async () => { ops.registry = await api('/api/registry?' + new URLSearchParams({ start: state.start, end: state.end, org: state.org, category: state.category, route: ops.filters.route, unit: ops.filters.unit })); if (state.view === 'registry') renderMain(); });
}
QaldyqViews.registry = {
  label: 'Бірыңғай тізілім', icon: 'file', roles: ['operator', 'reviewer', 'manager', 'admin'], load: loadRegistry, reload: true,
  render() {
    const r = ops.registry, table = (rows, a, b) => `<div class="table-scroll"><table><thead><tr><th>${a}</th>${b ? `<th>${b}</th>` : ''}<th class="numeric">САНЫ</th><th class="numeric">ЖАЗБА</th></tr></thead><tbody>${rows.map(x => `<tr><td>${esc(x.a)}</td>${b ? `<td>${esc(x.b)}</td>` : ''}<td class="numeric nowrap">${qtyUnit(x.quantity, x.unit)}</td><td class="numeric">${x.records}</td></tr>`).join('') || `<tr><td colspan="4">Таңдалған сүзгіде қабылданған өлшем жоқ.</td></tr>`}</tbody></table></div>`;
    return heading('Бірыңғай тізілім', 'Тек қабылданған өлшемдер. Сүзгі жеке өлшем жолдарын таңдайды.') + filters() +
      `<section class="panel food-panel"><div class="food-actions"><label>Кәдеге жарату тәсілі<select id="registry-route"><option value="">Барлық тәсіл</option>${routeList().map(x => `<option value="${esc(x.code)}" ${ops.filters.route === x.code ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label><label>Өлшем бірлігі<select id="registry-unit"><option value="">кг және л</option><option value="kg" ${ops.filters.unit === 'kg' ? 'selected' : ''}>кг</option><option value="l" ${ops.filters.unit === 'l' ? 'selected' : ''}>л</option></select></label><button class="btn primary" data-xlsx="">${icon('download')} Жиынтық есеп · Excel (XLSX)</button><button class="btn secondary" data-print="">PDF / басып шығару</button><button class="btn secondary" data-xlsx="journal">Жұмыс журналы · барлық мәртебе</button></div><p class="data-note">Жиынтық есеп пен PDF тек қабылданған деректерден жасалады. «Жұмыс журналы» барлық мәртебедегі жазбаларды қамтиды және файлдың өзінде солай белгіленеді. Килограмм мен литр бөлек есептеледі.</p></section>` +
      (r ? `<div class="food-kpis"><article class="panel"><span>Қабылданған мөлшер</span><strong>${unitTotals(r.summary.totals)}</strong><p>${r.measurements.length} өлшем жолы</p></article><article class="panel"><span>Ұйымдар бойынша</span><strong>${new Set(r.measurements.map(m => m.org_id)).size}</strong><p>Таңдалған кезеңде қабылданған өлшемі бар ұйым</p></article></div><section class="panel"><div class="panel-title"><div><h2>Ұйым және қалдық түрі бойынша</h2></div></div>${table(r.summary.by_org_type, 'ҰЙЫМ', 'ҚАЛДЫҚ ТҮРІ')}</section><section class="panel"><div class="panel-title"><div><h2>Айлар бойынша</h2></div></div>${table(r.summary.by_month, 'АЙ', 'ҰЙЫМ')}</section><section class="panel"><div class="panel-title"><div><h2>Өлшемдер</h2><p>${r.measurements.length > 100 ? 'Алғашқы 100 жол. Толық тізім — Excel файлында.' : 'Барлық жол'}</p></div></div><div class="table-scroll"><table><thead><tr><th>КҮНІ</th><th>ҰЙЫМ</th><th>ҚАЛДЫҚ ТҮРІ</th><th class="numeric">САНЫ</th><th>КӘДЕГЕ ЖАРАТУ ТӘСІЛІ</th><th>КЕЗЕҢІ</th><th>ЖАУАПТЫ</th></tr></thead><tbody>${r.measurements.slice(0, 100).map(m => `<tr><td class="nowrap">${esc(m.date)}</td><td>${esc(m.org_name)}</td><td>${esc(m.waste)}</td><td class="numeric nowrap">${qtyUnit(m.quantity, m.unit)}</td><td>${esc(m.route_name || m.route)}</td><td>${stageNames[m.stage] || ''}</td><td>${esc(m.responsible)}</td></tr>`).join('') || '<tr><td colspan="7">Жазба жоқ.</td></tr>'}</tbody></table></div></section>` : '<section class="panel food-panel">Жүктелуде…</section>');
  },
  bind() {
    $('#registry-route').onchange = e => { ops.filters.route = e.target.value; loadRegistry(); };
    $('#registry-unit').onchange = e => { ops.filters.unit = e.target.value; loadRegistry(); };
    $$('[data-xlsx]').forEach(b => b.onclick = () => { location.href = exportUrl({ format: 'xlsx', ...(b.dataset.xlsx ? { scope: 'journal' } : {}) }); });
    $$('[data-print]').forEach(b => b.onclick = () => window.open(exportUrl({ format: 'print' }), '_blank', 'noopener'));
  },
};

/* ---------- Users (ТТ 3) ---------- */
async function loadUsers() { await guarded(async () => { ops.users = (await api('/api/users')).users; if (state.view === 'users') renderMain(); }); }
QaldyqViews.users = {
  label: 'Пайдаланушылар', icon: 'building', roles: ['admin'], load: loadUsers,
  render() {
    return heading('Пайдаланушылар', 'Рөл мен ұйымды әкімші тағайындайды. Студенттер өздері тіркеледі және қызметтік рөл ала алмайды.', `<button class="btn primary" id="user-add">${icon('plus')} Пайдаланушы қосу</button>`) +
      `<section class="panel"><div class="table-scroll"><table><thead><tr><th>АТЫ-ЖӨНІ</th><th>EMAIL</th><th>РӨЛІ</th><th>ҰЙЫМЫ</th><th>КҮЙІ</th><th></th></tr></thead><tbody>${(ops.users || []).map(u => `<tr><td data-i18n-skip>${esc(u.name)}</td><td data-i18n-skip>${esc(u.email)}</td><td>${roleLabels[u.role]}${u.role === 'admin' && u.can_review ? ' + тексеру' : ''}</td><td>${esc(orgName(u.org_id)) || '—'}</td><td><span class="badge ${u.active ? 'accepted' : 'returned'}"><i></i>${u.active ? 'Белсенді' : 'Өшірілген'}</span></td><td><button class="btn secondary small" data-user="${u.id}">Өзгерту</button></td></tr>`).join('') || '<tr><td colspan="6">Жүктелуде…</td></tr>'}</tbody></table></div></section>`;
  },
  bind() { $('#user-add').onclick = () => openUser(); $$('[data-user]').forEach(b => b.onclick = () => openUser(ops.users.find(u => u.id === Number(b.dataset.user)))); },
};
function openUser(u = null) {
  openDialog(dialogHeading(u ? 'Пайдаланушыны өзгерту' : 'Пайдаланушы қосу') + `<form id="user-form"><div class="detail-body">${u ? `<p class="small muted" data-i18n-skip>${esc(u.email)}</p>` : field('user-email', 'Email', '', 'type="email" required autocomplete="off"')}${field('user-name', 'Аты-жөні', u?.name, 'required minlength="2" maxlength="80"')}<label>Рөлі<select id="user-role">${Object.entries(roleLabels).map(([k, v]) => `<option value="${k}" ${u?.role === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label><label>Ұйымы <span class="muted">(жауапты қызметкерге міндетті)</span><select id="user-org"><option value="0">—</option>${state.boot.organizations.map(o => `<option value="${o.id}" ${u?.org_id === o.id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select></label>${checkbox('user-review', 'Әкімшіге тексеру міндетін қоса беру', u?.can_review)}${u ? checkbox('user-active', 'Аккаунт белсенді', u.active) : ''}${field('user-password', u ? 'Жаңа құпиясөз (өзгертпесе бос қалдырыңыз)' : 'Құпиясөз (кемінде 8 таңба)', '', `type="password" autocomplete="new-password" minlength="8" ${u ? '' : 'required'}`)}<p class="form-error" id="user-error" role="alert"></p></div><div class="dialog-footer"><button type="button" class="btn secondary" data-close>Бас тарту</button><button class="btn primary" type="submit">Сақтау</button></div></form>`);
  $('#user-form').onsubmit = async e => {
    e.preventDefault();
    const body = { name: $('#user-name').value, role: $('#user-role').value, org_id: Number($('#user-org').value), can_review: $('#user-review').checked, ...(u ? { active: $('#user-active').checked } : { email: $('#user-email').value }), ...($('#user-password').value ? { password: $('#user-password').value } : {}) };
    try { await api(u ? '/api/users/' + u.id : '/api/users', { method: u ? 'PUT' : 'POST', body }); $('#dialog').close(); toast('Пайдаланушы сақталды.'); await loadUsers(); }
    catch (error) { $('#user-error').textContent = error.message; }
  };
}

/* ---------- Dictionaries (ТТ 2, 4) ---------- */
async function refreshBoot() { const fresh = await api('/api/bootstrap'); state.boot = fresh; renderMain(); }
QaldyqViews.dictionary = {
  label: 'Анықтамалықтар', icon: 'book', roles: ['reviewer', 'admin'],
  render() {
    const b = state.boot;
    return heading('Анықтамалықтар', 'Қалдық түрлері, кәдеге жарату тәсілдері және ұйымдар. Өлшемі бар түр өшірілмейді — тек белсенділігі тоқтатылады.') +
      `<section class="panel"><div class="panel-title"><div><h2>Қалдық түрлері</h2><p>CO₂ коэффициентінің дереккөзі мен есеп шекарасы әр түрде көрсетіледі</p></div><button class="btn secondary" data-action="add-category">${icon('plus')} Санат қосу</button></div><div class="table-scroll"><table><thead><tr><th>САНАТ</th><th>БІРЛІК</th><th>ӘДЕПКІ ТӘСІЛ</th><th class="numeric">CO₂</th><th>ДЕРЕККӨЗ</th><th>КҮЙІ</th><th></th></tr></thead><tbody>${b.categories.map(c => `<tr><td>${esc(c.name)}${c.recyclable ? ' <span class="muted">· қайта өңдеуге жарамды</span>' : ''}</td><td>${unitNames[c.unit]}</td><td>${esc(routeName(c.default_route))}</td><td class="numeric nowrap">${fmt(c.co2, 2)}</td><td class="small">${esc(c.source || '—')}</td><td><span class="badge ${c.active ? 'accepted' : 'returned'}"><i></i>${c.active ? 'Белсенді' : 'Өшірілген'}</span></td><td><button class="btn secondary small" data-cat="${c.id}">Өзгерту</button></td></tr>`).join('')}</tbody></table></div></section>` +
      `<section class="panel"><div class="panel-title"><div><h2>Кәдеге жарату тәсілдері</h2><p>Тізім кодты өзгертпей толықтырылады</p></div><button class="btn secondary" id="route-add">${icon('plus')} Тәсіл қосу</button></div><div class="table-scroll"><table><thead><tr><th>ТӘСІЛ</th><th>ӨҢДЕУГЕ БАҒЫТТАЛАДЫ</th><th>КҮЙІ</th><th></th></tr></thead><tbody>${b.routes.map(r => `<tr><td>${esc(r.name)}</td><td>${r.diverted ? 'Иә' : 'Жоқ'}</td><td><span class="badge ${r.active ? 'accepted' : 'returned'}"><i></i>${r.active ? 'Белсенді' : 'Өшірілген'}</span></td><td><button class="btn secondary small" data-route="${esc(r.code)}">Өзгерту</button></td></tr>`).join('')}</tbody></table></div></section>` +
      (isAdmin() ? `<section class="panel"><div class="panel-title"><div><h2>Ұйымдар</h2><p>Мекенжай, жұмыс уақыты және жауапты тұлғалар</p></div><button class="btn secondary" data-action="add-org">${icon('plus')} Ұйым қосу</button></div><div class="table-scroll"><table><thead><tr><th>ҰЙЫМ</th><th>ТҮРІ</th><th>МЕКЕНЖАЙЫ</th><th>ЖҰМЫС УАҚЫТЫ</th><th>ЖАУАПТЫЛАР</th><th>КҮЙІ</th><th></th></tr></thead><tbody>${b.organizations.map(o => `<tr><td>${esc(o.name)}</td><td>${esc(o.kind)}</td><td>${esc(o.address || '—')}</td><td>${esc(o.hours || '—')}</td><td data-i18n-skip>${esc((o.responsible || []).join(', ') || '—')}</td><td><span class="badge ${o.active ? 'accepted' : 'returned'}"><i></i>${o.active ? 'Белсенді' : 'Өшірілген'}</span></td><td><button class="btn secondary small" data-org-edit="${o.id}">Өзгерту</button></td></tr>`).join('')}</tbody></table></div></section>` : '');
  },
  bind() {
    $$('[data-cat]').forEach(b => b.onclick = () => openCategory(state.boot.categories.find(c => c.id === Number(b.dataset.cat))));
    $$('[data-route]').forEach(b => b.onclick = () => openRoute(state.boot.routes.find(r => r.code === b.dataset.route)));
    $('#route-add').onclick = () => openRoute();
    $$('[data-org-edit]').forEach(b => b.onclick = () => openOrg(state.boot.organizations.find(o => o.id === Number(b.dataset.orgEdit))));
  },
};
function dictionaryForm(title, body, save) {
  openDialog(dialogHeading(title) + `<form id="dict-form"><div class="detail-body">${body}<p class="form-error" id="dict-error" role="alert"></p></div><div class="dialog-footer"><button type="button" class="btn secondary" data-close>Бас тарту</button><button class="btn primary" type="submit">Сақтау</button></div></form>`);
  $('#dict-form').onsubmit = async e => { e.preventDefault(); try { await save(); $('#dialog').close(); toast('Анықтамалық жаңартылды.'); await refreshBoot(); } catch (error) { $('#dict-error').textContent = error.message; } };
}
function openCategory(c) {
  dictionaryForm('Қалдық түрін өзгерту', `<p><strong>${esc(c.name)}</strong></p>${field('cat-ru', 'Орысша атауы', c.name_ru, 'maxlength="120"')}<div class="form-grid"><label>Өлшем бірлігі<select id="cat-unit"><option value="kg" ${c.unit === 'kg' ? 'selected' : ''}>кг</option><option value="l" ${c.unit === 'l' ? 'selected' : ''}>л</option></select></label><label>Әдепкі кәдеге жарату тәсілі<select id="cat-route">${routeList().map(r => `<option value="${esc(r.code)}" ${c.default_route === r.code ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select></label></div><div class="form-grid">${field('cat-cost', 'Құн бағасы, ₸ / бірлік', c.cost, 'type="number" min="0" step="0.01" required')}${field('cat-co2', 'CO₂ коэффициенті', c.co2, 'type="number" min="0" max="1000" step="0.01" required')}</div>${field('cat-co2-unit', 'Коэффициент бірлігі', c.co2_unit, 'maxlength="40" required')}${field('cat-source', 'Коэффициент дереккөзі', c.source, 'maxlength="300"')}${field('cat-boundary', 'Есеп шекарасы', c.boundary, 'maxlength="300"')}${checkbox('cat-recyclable', 'Қайта өңдеуге жарамды', c.recyclable)}${checkbox('cat-active', 'Белсенді (формаларда көрсетіледі)', c.active)}`,
    () => api('/api/categories/' + c.id, { method: 'PUT', body: { name_ru: $('#cat-ru').value, unit: $('#cat-unit').value, default_route: $('#cat-route').value, cost: $('#cat-cost').value, co2: $('#cat-co2').value, co2_unit: $('#cat-co2-unit').value, source: $('#cat-source').value, boundary: $('#cat-boundary').value, recyclable: $('#cat-recyclable').checked, active: $('#cat-active').checked } }));
}
function openRoute(r = null) {
  dictionaryForm(r ? 'Тәсілді өзгерту' : 'Тәсіл қосу', `${field('route-name', 'Атауы', r?.name, 'required minlength="2" maxlength="80"')}${field('route-ru', 'Орысша атауы', r?.name_ru, 'maxlength="80"')}${checkbox('route-diverted', 'Өңдеуге бағытталады (қоқысқа емес)', r?.diverted)}${r ? checkbox('route-active', 'Белсенді', r.active) : ''}`,
    () => api(r ? '/api/routes/' + r.code : '/api/routes', { method: r ? 'PUT' : 'POST', body: { name: $('#route-name').value, name_ru: $('#route-ru').value, diverted: $('#route-diverted').checked, ...(r ? { active: $('#route-active').checked } : {}) } }));
}
function openOrg(o) {
  dictionaryForm('Ұйымды өзгерту', `${field('org-name', 'Атауы', o.name, 'required minlength="2" maxlength="120"')}${field('org-ru', 'Орысша атауы', o.name_ru, 'maxlength="120"')}<div class="form-grid">${field('org-kind', 'Түрі', o.kind, 'required maxlength="80"')}${field('org-short', 'Қысқа атауы', o.short, 'maxlength="12"')}</div>${field('org-address', 'Корпус / мекенжай', o.address, 'maxlength="200"')}${field('org-hours', 'Жұмыс уақыты', o.hours, 'maxlength="120"')}${field('org-description', 'Сипаттама', o.description, 'maxlength="500"')}${checkbox('org-public', 'Студенттерге ашық тамақтану орны', o.is_public)}${checkbox('org-active', 'Белсенді', o.active)}`,
    () => api('/api/organizations/' + o.id, { method: 'PUT', body: { name: $('#org-name').value, name_ru: $('#org-ru').value, kind: $('#org-kind').value, short: $('#org-short').value, address: $('#org-address').value, hours: $('#org-hours').value, description: $('#org-description').value, is_public: $('#org-public').checked, active: $('#org-active').checked } }));
}

/* ---------- Quick entry (ТТ 21): open → type → quantity → save ---------- */
function openQuick() {
  const org = state.boot.user.org_id || Number(state.org) || state.boot.organizations[0].id, cats = orgCategories(org).filter(c => c.active !== 0);
  let chosen = cats[0];
  openDialog(dialogHeading('Жылдам енгізу', `${esc(orgName(org))} · бүгін`) + `<form id="quick-form"><div class="detail-body"><div class="chip-row" role="group" aria-label="Қалдық түрі">${cats.map(c => `<button type="button" class="chip ${c === chosen ? 'selected' : ''}" data-quick-cat="${c.id}">${esc(c.name)}</button>`).join('')}</div><label>Саны, <b id="quick-unit">${unitNames[chosen?.unit] || 'кг'}</b><input id="quick-kg" type="number" inputmode="decimal" min="0.01" max="10000" step="0.01" required placeholder="0.00"></label><p class="small muted" id="quick-route"></p><p class="form-error" id="quick-error" role="alert"></p><p class="small" id="quick-done" role="status"></p></div><div class="dialog-footer"><button type="button" class="btn secondary" data-close>Жабу</button><button class="btn primary" type="submit">${icon('check')} Сақтау</button></div></form>`);
  const sync = () => { $('#quick-unit').textContent = unitNames[chosen.unit] || 'кг'; $('#quick-route').textContent = 'Кәдеге жарату тәсілі: ' + routeName(chosen.default_route); $$('[data-quick-cat]').forEach(b => b.classList.toggle('selected', Number(b.dataset.quickCat) === chosen.id)); };
  $$('[data-quick-cat]').forEach(b => b.onclick = () => { chosen = cats.find(c => c.id === Number(b.dataset.quickCat)); sync(); $('#quick-kg').focus(); });
  if (chosen) sync(); $('#quick-kg').focus();
  $('#quick-form').onsubmit = async e => {
    e.preventDefault(); const kg = Number($('#quick-kg').value), payload = { org_id: org, category_id: chosen.id, kg, request_id: uuid() };
    $('#quick-error').textContent = '';
    try {
      if (!navigator.onLine) throw Object.assign(new Error('offline'), { network: true });
      const result = await api('/api/quick', { method: 'POST', body: payload });
      $('#quick-done').textContent = `Сақталды: ${chosen.name} — ${fmt(kg, 2)} ${unitNames[chosen.unit]}. Бүгінгі жиыны: ${fmt(result.day_total, 2)} ${unitNames[chosen.unit]}.` + (result.duplicates.length ? ' Назар аударыңыз: осындай өлшем бүгін тіркелген.' : '');
      $('#quick-kg').value = ''; $('#quick-kg').focus(); loadData();
    } catch (error) {
      if (!error.network) return void ($('#quick-error').textContent = error.message);
      // Offline: keep the measurement in the durable queue; it is sent once under the same request key.
      await QStore.put({ key: payload.request_id, user: state.boot.user.id, path: '/api/quick', method: 'POST', payload: { ...payload, report_date: state.boot.today, items: [{ category_id: chosen.id, kg }] }, created: new Date().toISOString(), error: null });
      $('#quick-done').textContent = 'Байланыс жоқ. Өлшем құрылғыға сақталды және байланыс қосылғанда жіберіледі.'; $('#quick-kg').value = ''; refreshOfflineStatus();
    }
  };
}

/* ---------- Account switch: sign out and sign in as another demo user ---------- */
async function openSwitch() {
  let accounts = [];
  try { accounts = (await api('/api/public/demo-accounts')).accounts; } catch { /* list stays empty */ }
  openDialog(dialogHeading('Аккаунтты ауыстыру', 'Ағымдағы сессия жабылып, таңдалған аккаунтпен кіресіз.') + `<div class="detail-body"><p class="small muted">Қазір: <strong data-i18n-skip>${esc(state.boot.user.name)}</strong> · ${roleLabels[state.boot.user.role]}</p>${accounts.length ? `<div class="account-list">${accounts.map(a => `<button class="account-row" data-switch="${esc(a.email)}"><strong data-i18n-skip>${esc(a.name)}</strong><span>${roleLabels[a.role]}${a.org_name ? ' · ' + esc(a.org_name) : ''}</span><small data-i18n-skip>${esc(a.email)}</small></button>`).join('')}</div><p class="small muted">Демо аккаунттардың құпиясөзі: <strong>demo2026</strong>. Нақты енгізуде бұл тізім өшіріледі.</p>` : '<p>Демо аккаунттар тізімі өшірілген. Шығып, өз аккаунтыңызбен кіріңіз.</p>'}<p class="form-error" id="switch-error" role="alert"></p></div><div class="dialog-footer"><button class="btn secondary" data-close>Жабу</button><button class="btn danger" id="switch-logout">${icon('logout')} Жүйеден шығу</button></div>`);
  $('#switch-logout').onclick = () => { $('#dialog').close(); $('#logout').click(); };
  $$('[data-switch]').forEach(b => b.onclick = () => switchAccount(b.dataset.switch));
}
async function switchAccount(email, password = 'demo2026') {
  try {
    await api('/api/logout', { method: 'POST', body: {} });
    await QStore.del('boot'); await QStore.del('active-user'); state.boot = null; csrf = '';
    const result = await api('/api/login', { method: 'POST', body: { email, password } });
    if ($('#dialog').open) $('#dialog').close();
    if (result.role === 'student') return void (location.href = '/student/');
    await boot();
  } catch (error) { const el = $('#switch-error'); if (el) el.textContent = error.message; else toast(error.message, true); if (!state.boot) renderLogin(); }
}
