const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function setup(saved,blocked=false){
  const storage=new Map(saved?[['qaldyq-language',saved]]:[]),listeners={};
  const scope={window:{},document:{readyState:'loading',body:null,addEventListener:(name,fn)=>listeners[name]=fn,dispatchEvent:()=>{}},localStorage:{getItem:key=>{if(blocked)throw Error('storage blocked');return storage.get(key);},setItem:(key,value)=>{if(blocked)throw Error('storage blocked');storage.set(key,value);}},CustomEvent:class{}};
  vm.runInNewContext(fs.readFileSync('static/i18n.js','utf8'),scope);
  return {i18n:scope.window.QaldyqI18n,storage};
}
test('defaults to Kazakh; Russian choice persists and can be reversed',()=>{
  const {i18n,storage}=setup();assert.equal(i18n.text('Жаңа есеп'),'Жаңа есеп');
  i18n.setLanguage('ru');assert.equal(i18n.text('Жаңа есеп'),'Новый отчёт');assert.equal(storage.get('qaldyq-language'),'ru');
  i18n.setLanguage('kk');assert.equal(i18n.text('Жаңа есеп'),'Жаңа есеп');
});
test('saved language is restored; unsupported language is ignored',()=>{
  const {i18n}=setup('ru');assert.equal(i18n.language,'ru');i18n.setLanguage('en');assert.equal(i18n.language,'ru');
  assert.equal(setup('invalid').i18n.language,'kk');
});
test('private mode storage errors do not prevent switching',()=>{
  const {i18n}=setup(null,true);i18n.setLanguage('ru');assert.equal(i18n.text('Сақтау'),'Сохранить');
});
test('dynamic counts and dates preserve actual numeric data',()=>{
  const {i18n}=setup('ru');
  assert.equal(i18n.text('24 кг ÷ 510 порция × 100'),'24 кг ÷ 510 порций × 100');
  assert.equal(i18n.text('100 порцияға: 4,71 кг'),'На 100 порций: 4,71 кг');
  assert.equal(i18n.text('1 қаз. – 30 қаз.'),'1 окт. – 30 окт.');
  assert.equal(i18n.text('2026-10-31 күніне дайындау ұсынысы'),'Рекомендация по приготовлению на 2026-10-31');
});
test('Russian quantities use appropriate forms',()=>{
  const {i18n}=setup('ru');
  for(const [source,output] of [['1 порция','1 порция'],['2 порция','2 порции'],['11 порция','11 порций'],['179 порция','179 порций'],['21 күндік жиынтық','Итог за 21 день']])assert.equal(i18n.text(source),output);
});
test('unknown authored content and whitespace remain unchanged',()=>{
  const {i18n}=setup('ru');
  for(const source of ['NOVA','Палау, автор рецепта — Алия','Менің бүгінгі есебім: 150 порция','  ','https://example.kz/?org=2'])assert.equal(i18n.text(source),source);
  assert.equal(i18n.text('  Сақтау  '),'  Сохранить  ');
});
test('organization names translate in tables, options and combined report labels',()=>{
  const {i18n}=setup('ru');
  assert.equal(i18n.text('1-корпус асханасы'),'Столовая корпуса №1');
  assert.equal(i18n.text('2С корпус асханасы'),'Столовая корпуса 2С');
  assert.equal(i18n.text('Тағам технологиясы кафедрасы'),'Кафедра пищевых технологий');
  assert.equal(i18n.text('1-корпус асханасы · 30 қаз.'),'Столовая корпуса №1 · 30 окт.');
  assert.equal(i18n.text('Тағам технологиясы кафедрасы · есеп күтілуде'),'Кафедра пищевых технологий · ожидается отчёт');
  assert.equal(i18n.text('Жүйе әкімшісі · 30/10/2026, 12:36'),'Администратор системы · 30/10/2026, 12:36');
  i18n.setLanguage('kk');assert.equal(i18n.text('1-корпус асханасы'),'1-корпус асханасы');
});
test('entity substitution does not partially rename unrelated custom organizations',()=>{
  const {i18n}=setup('ru');
  assert.equal(i18n.text('NOVA асханасы'),'NOVA асханасы');
  assert.equal(i18n.text('1-корпус асханасының дүкені'),'1-корпус асханасының дүкені');
  assert.equal(i18n.text('Campus Coffee'),'Campus Coffee');
});
