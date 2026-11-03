/* Shared by the page and service worker. Reports and photos stay in IndexedDB. */
(function(root){
  let connection;
  function db(){return connection ||= new Promise((resolve,reject)=>{const r=indexedDB.open('qaldyq-offline-v4',1);r.onupgradeneeded=()=>{r.result.createObjectStore('meta');r.result.createObjectStore('queue',{keyPath:'key'});};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  async function operation(store,mode,action){const d=await db();return new Promise((resolve,reject)=>{const t=d.transaction(store,mode);const request=action(t.objectStore(store));let value;request.onsuccess=()=>{value=request.result;};t.oncomplete=()=>resolve(value);t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||new Error('Жергілікті сақтау орындалмады.'));});}
  const api={get:key=>operation('meta','readonly',s=>s.get(key)),set:(key,value)=>operation('meta','readwrite',s=>s.put(value,key)),del:key=>operation('meta','readwrite',s=>s.delete(key)),tasks:()=>operation('queue','readonly',s=>s.getAll()),put:task=>operation('queue','readwrite',s=>s.put(task)),remove:key=>operation('queue','readwrite',s=>s.delete(key))};
  async function sync(){
    const response=await fetch('/api/bootstrap',{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)return {sent:0,auth:response.status===401};
    const boot=await response.json();let sent=0;
    for(const task of await api.tasks()){
      if(task.user!==boot.user.id||task.error)continue;
      let result;
      try{result=await fetch(task.path,{method:task.method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':boot.csrf},body:JSON.stringify(task.payload)});}catch{break;}
      if(result.ok){await api.remove(task.key);sent++;}
      else {if(result.status===401)break;if(result.status>=500)break;const data=await result.json();task.error=data.error||'Есепті тексеріңіз.';await api.put(task);}
    }
    return {sent};
  }
  // Web Locks prevents a page and its service worker from racing the same edit.
  api.sync=()=>root.navigator?.locks?root.navigator.locks.request('qaldyq-sync',sync):sync();
  root.QStore=api;
})(globalThis);
