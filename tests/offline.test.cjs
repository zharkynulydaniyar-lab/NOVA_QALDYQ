const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function setup(tasks,responses){
  const calls=[],removed=[],saved=[];
  const scope={navigator:{locks:{request:async(name,fn)=>{assert.equal(name,'qaldyq-sync');return fn();}}},fetch:async(path,options)=>{calls.push({path,options});const next=responses.shift();if(next instanceof Error)throw next;return {ok:next.status<400,status:next.status,json:async()=>next.body};}};
  vm.runInNewContext(fs.readFileSync('static/offline-store.js','utf8'),scope);
  scope.QStore.tasks=async()=>tasks;
  scope.QStore.remove=async key=>removed.push(key);
  scope.QStore.put=async task=>saved.push(task);
  return {...scope,calls,removed,saved};
}
const boot={status:200,body:{user:{id:1},csrf:'fresh-token'}};
const task=(key,user=1)=>({key,user,path:'/api/reports',method:'POST',payload:{request_id:key}});
test('sync sends only the signed-in employee queue, with refreshed CSRF',async()=>{
  const s=setup([task('mine'),task('other',2)],[boot,{status:201}]);
  assert.equal((await s.QStore.sync()).sent,1);assert.deepEqual(s.removed,['mine']);assert.equal(s.calls.length,2);
  assert.equal(s.calls[1].options.headers['X-CSRF-Token'],'fresh-token');
});
test('disconnect retains the report and stops sending',async()=>{
  const s=setup([task('one'),task('two')],[boot,new Error('offline')]);
  assert.equal((await s.QStore.sync()).sent,0);assert.equal(s.removed.length,0);assert.equal(s.calls.length,2);
});
test('validation and permission errors remain visible without retry loops',async()=>{
  const s=setup([task('one')],[boot,{status:403,body:{error:'Wrong organization'}}]);
  await s.QStore.sync();assert.equal(s.saved[0].error,'Wrong organization');assert.equal(s.removed.length,0);
});
test('expired session does not discard data',async()=>{
  const s=setup([task('one')],[{status:401}]);
  assert.equal((await s.QStore.sync()).auth,true);assert.equal(s.removed.length,0);assert.equal(s.calls.length,1);
});
test('server failure retains queue for automatic retry',async()=>{
  const s=setup([task('one')],[boot,{status:500}]);
  await s.QStore.sync();assert.equal(s.saved.length,0);assert.equal(s.removed.length,0);
});
test('conflicts remain queued and require review',async()=>{
  const s=setup([task('one')],[boot,{status:409,body:{error:'Version changed'}}]);
  await s.QStore.sync();assert.equal(s.saved[0].error,'Version changed');assert.equal(s.removed.length,0);
});
