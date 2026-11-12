const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

function setup(){
  const elements={},qrInputs=[],blobs=[];
  const scope={console,URL,URLSearchParams,Intl,Date,crypto:require('node:crypto').webcrypto,
    navigator:{onLine:true},window:{},location:{origin:'https://old-domain.test'},
    document:{querySelector:s=>elements[s]||null,querySelectorAll:s=>elements[s]||[],createElement:()=>({click(){}})},
    QaldyqI18n:{language:'kk'},
    qrcode:()=>({addData:value=>qrInputs.push(value),make(){},createSvgTag:()=>'<svg></svg>'}),
    Blob:class{constructor(parts){blobs.push(parts.join(''));}},setTimeout(){},clearTimeout(){}};
  vm.createContext(scope);
  vm.runInContext(fs.readFileSync('static/app.js','utf8').replace(/\nboot\(\);\s*$/,''),scope);
  vm.runInContext(fs.readFileSync('static/features.js','utf8'),scope);
  const run=code=>vm.runInContext(code,scope);
  run("state.boot={user:{id:1,role:'operator',org_id:1},telegram:{url:'https://t.me/Qalqyq_NOVA_bot'},organizations:[{id:1,name:'Canteen',kind:'Асхана'}]};heading=()=>'';");
  return {scope,run,elements,qrInputs,blobs};
}

test('QR tab adds the bot card while keeping the original organization QR',()=>{
  const s=setup();const html=s.run('qrView()');
  assert.match(html,/telegram-qr-card/);
  assert.match(html,/https:\/\/t\.me\/Qalqyq_NOVA_bot/);
  assert.match(html,/telegram-qr-download/);
  assert.match(html,/data-qr-download="1"/);
  assert.deepEqual(s.qrInputs,['https://t.me/Qalqyq_NOVA_bot','https://old-domain.test/?org=1#new-report']);
});

test('changing application domain never changes the Telegram bot QR data',()=>{
  const s=setup();s.run('qrView()');s.scope.location.origin='https://new-domain.test';s.run('qrView()');
  assert.equal(s.qrInputs[0],s.qrInputs[2]);
  assert.equal(s.qrInputs[3],'https://new-domain.test/?org=1#new-report');
});

test('refreshing canteen QR base preserves the separate bot card and its stable link',()=>{
  const s=setup();s.elements['#qr-refresh']={};s.elements['#qr-base']={value:'https://campus.example.kz'};s.elements['#qr-cards']={innerHTML:''};s.elements['#qr-error']={};
  s.run('bindQr()');s.elements['#qr-refresh'].onclick();
  assert.match(s.elements['#qr-cards'].innerHTML,/campus\.example\.kz/);
  assert.equal(s.run('state.boot.telegram.url'),'https://t.me/Qalqyq_NOVA_bot');
});

test('student Mini App uses raw initData header without cookies or storing credentials',async()=>{
  const calls=[];
  const scope={window:{Telegram:{WebApp:{initData:'signed-init-data'}}},document:{querySelector:()=>({hidden:false,textContent:''}),querySelectorAll:()=>[]},
    navigator:{onLine:true},localStorage:{getItem:()=>null},fetch:async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>({})};},console};
  vm.createContext(scope);vm.runInContext(fs.readFileSync('static/student/student.js','utf8').replace(/\nstart\(\);\s*$/,''),scope);
  await vm.runInContext("api('/api/student/orders',{method:'POST',body:{request_id:'same-shared-order-key'}})",scope);
  assert.equal(calls[0].options.headers.Authorization,'tma signed-init-data');
  assert.equal(calls[0].options.credentials,'omit');
  assert.equal(calls[0].path,'/api/student/orders');
});
