const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

function setup(){
  const elements={},timers=new Map(),saved=[],blobs=[];
  let timerId=0;
  const scope={console,URL,URLSearchParams,Intl,Date,crypto:require('node:crypto').webcrypto,
    navigator:{onLine:true},window:{},location:{origin:'http://localhost:8765'},
    document:{querySelector:s=>elements[s]||null,querySelectorAll:s=>elements[s]||[],createElement:()=>({click(){}})},
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
    QStore:{set:async(key,value)=>saved.push({key,value}),get:async()=>null},
    Blob:class{constructor(parts){blobs.push(parts.join(''));}},
  };
  vm.createContext(scope);
  vm.runInContext(fs.readFileSync('static/app.js','utf8').replace(/\nboot\(\);\s*$/,''),scope);
  vm.runInContext(fs.readFileSync('static/features.js','utf8'),scope);
  const run=code=>vm.runInContext(code,scope);
  run("state.boot={user:{id:1,role:'admin'},today:'2026-11-03',demo_date:'2026-10-30'};state.start='2026-11-01';state.end='2026-11-03';toast=()=>{};renderMain=()=>{};");
  return {scope,run,elements,timers,saved,blobs};
}

test('periods use today, including quarter and year boundaries; demo stays explicit',()=>{
  const {run}=setup();
  for(const [period,today,start,end=today] of [
    ['week','2027-01-02','2026-12-27'],['month','2026-11-03','2026-11-01'],
    ['quarter','2026-11-03','2026-10-01'],['quarter','2027-02-02','2027-01-01'],
    ['year','2027-01-02','2027-01-01'],['demo','2026-11-03','2026-10-01','2026-10-30'],
  ]){
    const range=run(`periodRange('${period}','${today}','2026-10-30')`);
    assert.equal(range.start,start);assert.equal(range.end,end);
  }
});

function form(s){
  for(const [key,value] of Object.entries({'form-org':'1','form-date':'2026-11-03','form-note':'Сақталған мәтін','form-portions':'150','save-mode':'submit'}))s.elements['#'+key]={value};
  s.elements['.waste-row']=[];s.elements['.dish-row']=[];s.elements['.remove-dish']=[];
  s.elements['#report-form']={addEventListener(){}};s.elements['#add-dish']={};
}

test('local draft retains submit mode, request identity and portions',()=>{
  const s=setup();form(s);
  const payload=s.run("captureForm({request_id:'stable-request'},null)");
  assert.equal(payload.submit,true);assert.equal(payload.request_id,'stable-request');assert.equal(payload.portions,150);
});

test('delayed autosave belongs to the form owner after account switch',async()=>{
  const s=setup();form(s);
  s.run("bindFoodForm({request_id:'old-user'},()=>null)();state.boot.user.id=2;");
  await [...s.timers.values()][0]();
  assert.equal(s.saved.length,1);assert.equal(s.saved[0].key,'draft:1');
});

test('delayed autosave survives logout without losing the draft',async()=>{
  const s=setup();form(s);
  s.run('bindFoodForm({},()=>null)();state.boot=null;');
  await [...s.timers.values()][0]();
  assert.equal(s.saved[0].key,'draft:1');
});

test('downloaded QR matches displayed card even with an unrefreshed base field',()=>{
  const s=setup();
  s.elements['[data-qr-open]']=[];
  const button={dataset:{qrDownload:'2'},closest:()=>({querySelector:()=>({href:'https://campus.example.kz/?org=2#new-report'})})};
  s.elements['[data-qr-download]']=[button];s.elements['#qr-base']={value:'not a URL'};
  s.scope.URL=class extends URL{static createObjectURL(){return 'blob:test';}static revokeObjectURL(){}};
  s.run('qrMarkup=url=>url;bindQrCards();');button.onclick();
  assert.equal(s.blobs[0],'https://campus.example.kz/?org=2#new-report');
});

test('inbox refresh preserves unsaved deadline while accepting the new server value',async()=>{
  const s=setup();s.elements['#deadline-day']={value:'17',defaultValue:'5'};
  s.scope.nextInbox={notifications:[],deadline_day:8};
  s.scope.newInput={value:'8',defaultValue:'8'};
  s.scope.elements=s.elements;
  s.run("state.view='notifications';api=async()=>nextInbox;renderMain=()=>{elements['#deadline-day']=newInput;};");
  await s.run('pollNotifications()');
  assert.equal(s.elements['#deadline-day'].value,'17');assert.equal(s.elements['#deadline-day'].defaultValue,'8');
});

test('failed period load cannot present previous period totals as current data',async()=>{
  const s=setup();s.elements['#pending-count']={};
  s.run("state.reports=[{kg:99}];state.previous=[{kg:88}];api=async()=>{throw Object.assign(new Error('offline'),{network:true});};");
  await s.run('loadData()');
  assert.equal(s.run('state.reports.length'),0);assert.equal(s.run('state.previous.length'),0);
  assert.equal(s.run('state.loadError'),'offline');
});

test('expiry during report loading returns to login without dereferencing the user',async()=>{
  const s=setup();
  s.run("api=async()=>{state.boot=null;throw new Error('expired');};");
  await s.run('loadData()');
  assert.equal(s.run('state.boot'),null);
});
