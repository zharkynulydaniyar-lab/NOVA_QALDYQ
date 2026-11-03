import * as THREE from './vendor/three.module.js';

// All actors, props and motion are authored here. No remote models or services.
const entries = new Map();
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const forceSoftware = new URLSearchParams(location.search).get('renderer') === 'software';
let paused = reduceMotion.matches;
let raf = 0, previous = 0, lastPaint = 0;
const C = {green:0x326549,dark:0x233e32,lime:0xd3eaa4,cream:0xf3edda,skin:0xe4b895,hair:0x44392f,ochre:0xd8a653,white:0xfffbef,blue:0x719a9c,gray:0xb6c3af,orange:0xe79b48};
const mat = (color, extra={}) => new THREE.MeshStandardMaterial({color,roughness:.73,metalness:.03,...extra});
const box = (w,h,d) => new THREE.BoxGeometry(w,h,d);
const sphere = (r, w=14,h=10) => new THREE.SphereGeometry(r,w,h);
const capsule = (r,length) => new THREE.CapsuleGeometry(r,length,4,10);
const cylinder = (top,bottom,h) => new THREE.CylinderGeometry(top,bottom,h,18);
function mesh(parent, geometry, material, x=0,y=0,z=0) {
  const object=new THREE.Mesh(geometry,material);object.position.set(x,y,z);object.castShadow=true;object.receiveShadow=true;parent.add(object);return object;
}
function group(parent,x=0,y=0,z=0){const g=new THREE.Group();g.position.set(x,y,z);parent.add(g);return g;}
function roundBox(w,h,d,r=.06){
  r=Math.min(r,w/4,h/4,d/4);
  const s=new THREE.Shape(),x=-w/2+r,y=-h/2+r,a=w/2-r,b=h/2-r;
  s.moveTo(x+r,y);s.lineTo(a-r,y);s.quadraticCurveTo(a,y,a,y+r);s.lineTo(a,b-r);s.quadraticCurveTo(a,b,a-r,b);s.lineTo(x+r,b);s.quadraticCurveTo(x,b,x,b-r);s.lineTo(x,y+r);s.quadraticCurveTo(x,y,x+r,y);
  const geo=new THREE.ExtrudeGeometry(s,{depth:d-2*r,bevelEnabled:true,bevelSize:r,bevelThickness:r,bevelSegments:2,steps:1,curveSegments:3});geo.translate(0,0,-d/2+r);return geo;
}
function label(parent,text,w=.7,h=.28,x=0,y=0,z=0,color='#dbf0b4',background='#244632'){
  const canvas=document.createElement('canvas');canvas.width=320;canvas.height=128;
  const context=canvas.getContext('2d');
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  const material=new THREE.MeshBasicMaterial({map:texture,transparent:true,side:THREE.DoubleSide});
  const panel=mesh(parent,new THREE.PlaneGeometry(w,h),material,x,y,z);
  function update(value){panel.userData.sourceText=value;value=window.QaldyqI18n?.text(value)||value;if(panel.userData.text===value)return;panel.userData.text=value;context.clearRect(0,0,320,128);context.fillStyle=background;context.beginPath();context.roundRect(0,0,320,128,18);context.fill();context.fillStyle=color;context.textAlign='center';context.textBaseline='middle';context.font='600 62px "Segoe UI", sans-serif';context.fillText(value,160,68);texture.needsUpdate=true;}
  panel.userData.refreshLanguage=()=>update(panel.userData.sourceText);
  update(text);return {object:panel,update};
}
function person(parent,shirt=C.green){
  const root=group(parent),hip=group(root,0,.94,0),body=group(hip);
  const skin=mat(C.skin),uniform=mat(shirt),trousers=mat(C.dark),shoes=mat(0x29372e),hair=mat(C.hair);
  mesh(body,capsule(.235,.28),uniform,0,.4,0);
  mesh(body,roundBox(.37,.36,.11,.035),mat(C.lime),0,.38,.2);
  mesh(body,box(.035,.17,.015),uniform,-.11,.65,.22);mesh(body,box(.035,.17,.015),uniform,.11,.65,.22);
  mesh(body,box(.12,.1,.018),mat(0xb0c685),.055,.39,.266);
  mesh(body,cylinder(.075,.08,.13),skin,0,.76,0);
  const head=group(body,0,1,0);
  mesh(head,sphere(.218,18,14),skin);
  const cap=mesh(head,new THREE.SphereGeometry(.225,18,10,0,Math.PI*2,0,Math.PI/2),uniform,0,.035,-.005);
  const brim=mesh(head,roundBox(.31,.035,.19,.015),uniform,0,.045,.16);brim.rotation.x=-.09;
  mesh(head,sphere(.036),skin,-.22,-.015,0);mesh(head,sphere(.036),skin,.22,-.015,0);
  for(const x of [-.073,.073]){mesh(head,sphere(.019,10,8),hair,x,-.012,.198);mesh(head,sphere(.006,8,6),mat(C.white),x+.005,-.007,.212);}
  mesh(head,sphere(.028),skin,0,-.047,.215);
  const smile=mesh(head,new THREE.TorusGeometry(.046,.006,5,12,Math.PI),hair,0,-.076,.201);smile.rotation.z=Math.PI;
  const arms=[];
  for(const side of [-1,1]){
    const shoulder=group(body,side*.27,.65,0);mesh(shoulder,capsule(.085,.22),uniform,0,-.17,0);
    const elbow=group(shoulder,0,-.34,0);mesh(elbow,capsule(.069,.2),skin,0,-.15,0);
    const hand=group(elbow,0,-.315,0);mesh(hand,sphere(.078),skin);
    arms.push({shoulder,elbow,hand});
  }
  const legs=[];
  for(const side of [-1,1]){
    const thigh=group(hip,side*.135,0,0);mesh(thigh,capsule(.103,.24),trousers,0,-.205,0);
    const knee=group(thigh,0,-.41,0);mesh(knee,capsule(.083,.23),trousers,0,-.18,0);
    mesh(knee,roundBox(.2,.14,.32,.04),shoes,0,-.35,.06);legs.push({thigh,knee});
  }
  return {root,hip,body,head,left:arms[0],right:arms[1],legs};
}
function plant(parent,x,z,scale=1){
  const p=group(parent,x,.09,z);p.scale.setScalar(scale);
  mesh(p,cylinder(.22,.17,.35),mat(C.cream),0,.17,0);
  mesh(p,cylinder(.18,.18,.025),mat(0x665039),0,.35,0);
  for(let i=0;i<5;i++){const a=i*2.4;const leaf=mesh(p,sphere(.16),mat(i%2?0x7ea561:0x62844e),Math.sin(a)*.12,.56+(i%2)*.14,Math.cos(a)*.12);leaf.scale.set(.6,1.7,.45);leaf.rotation.z=Math.sin(a)*.6;}
}
function bin(parent,x,z,color=C.green){
  const root=group(parent,x,.1,z);mesh(root,roundBox(.62,.79,.6,.08),mat(color),0,.42,0);
  const lid=group(root,0,.84,-.26);mesh(lid,roundBox(.68,.09,.65,.04),mat(color),0,0,.27);
  mesh(root,roundBox(.27,.065,.02,.015),mat(C.dark),0,.6,.309);
  label(root,'♻',.25,.21,0,.35,.321,'#e9f2d6',color===C.green?'#326549':'#a8bc79');
  for(const side of [-1,1]){const wheel=mesh(root,cylinder(.065,.065,.04),mat(C.dark),side*.23,.06,-.22);wheel.rotation.z=Math.PI/2;}
  return {root,lid};
}
function baseScene(kind){
  const scene=new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xfff9ed,0x6d8971,2.6));
  const sun=new THREE.DirectionalLight(0xfff4d8,3.4);sun.position.set(-3.5,7,5);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);sun.shadow.camera.left=-4;sun.shadow.camera.right=4;sun.shadow.camera.top=4;sun.shadow.camera.bottom=-4;sun.shadow.normalBias=.03;sun.shadow.bias=-.00015;sun.shadow.radius=4;scene.add(sun);
  const fill=new THREE.DirectionalLight(0xb7d6bf,1.5);fill.position.set(4,3,-3);scene.add(fill);
  const world=group(scene);world.rotation.y=-.13;
  mesh(world,cylinder(2.35,2.35,.16),mat(kind==='count'?0xe6ddc8:0xe5e9d0),0,-.01,0);
  mesh(world,cylinder(2.29,2.29,.025),mat(0xf2f0df),0,.08,0);
  for(let i=-2;i<=2;i++)mesh(world,box(3.7,.004,.009),mat(0xe0dfc8),0,.096,i*.7);
  return {scene,world};
}
function broom(parent){
  const b=group(parent,0,-.03,0);b.rotation.x=.06;
  mesh(b,cylinder(.023,.023,.95),mat(0xceb88c),0,-.29,0);
  mesh(b,roundBox(.42,.085,.16,.025),mat(C.green),0,-.79,0);
  for(let i=0;i<9;i++)mesh(b,box(.036,.13,.12),mat(i%2?0xc9ae6e:0xd8bf84),-.17+i*.042,-.88,0);
  return b;
}
function cleanScene(){
  const {scene,world}=baseScene('clean');
  const worker=person(world);worker.root.position.set(-.72,.07,.45);worker.root.rotation.y=.55;
  worker.right.shoulder.rotation.x=-.3;worker.right.elbow.rotation.x=-.16;broom(worker.right.hand);
  const trashBin=bin(world,1.35,-.52,C.green);bin(world,.62,-.93,C.lime);plant(world,-1.55,-.95,.85);
  const waste=[];
  for(let i=0;i<7;i++){const o=mesh(world,i%2?new THREE.DodecahedronGeometry(.09):new THREE.SphereGeometry(.085,8,6),mat([C.orange,C.lime,C.cream][i%3]),.1+i*.14,.17,.22+(i%3)*.19);o.scale.set(1,.45,1);o.rotation.y=i;waste.push(o);}
  return {scene,world,update(t){
    const c=(t%9)/9,sweep=Math.sin(t*3.5),walk=Math.sin(t*2.6);
    worker.root.position.x=-.78+Math.sin(t*.7)*.3;worker.root.position.z=.42+Math.cos(t*.7)*.08;worker.root.position.y=.07+Math.abs(walk)*.012;
    worker.body.rotation.x=.12;worker.body.rotation.z=sweep*.035;worker.head.rotation.y=.12+Math.sin(t*.8)*.14;
    worker.right.shoulder.rotation.x=-.31+sweep*.16;worker.right.shoulder.rotation.z=-.12+sweep*.18;worker.right.elbow.rotation.x=-.2;
    worker.left.shoulder.rotation.x=.12-walk*.09;
    worker.legs.forEach((l,i)=>{l.thigh.rotation.x=walk*(i?-.21:.21);l.knee.rotation.x=.035+Math.max(0,walk*(i?-1:1))*.11;});
    waste.forEach((o,i)=>{const p=THREE.MathUtils.clamp((c-.08-i*.06)*2.4,0,1);o.visible=p<.98;o.position.set(THREE.MathUtils.lerp(.12+i*.14,1.35,p),.17+Math.sin(p*Math.PI)*.1,THREE.MathUtils.lerp(.22+(i%3)*.19,-.52,p));o.rotation.z=p*4;});
    trashBin.lid.rotation.x=-Math.max(0,Math.sin(c*Math.PI))*.45;
    return c<.25?'Қалдықты бір жерге жинауда':c<.75?'Қалдықты сұрыптап жинауда':'Келесі аумаққа өтуде';
  }};
}
function bag(parent){const b=group(parent);mesh(b,sphere(.23),mat(C.ochre),0,.21,0).scale.set(1,1.08,.86);mesh(b,new THREE.ConeGeometry(.085,.15,8),mat(C.ochre),0,.48,0);mesh(b,cylinder(.045,.045,.035),mat(C.green),0,.43,0);return b;}
function weighScene(){
  const {scene,world}=baseScene('weigh');
  const worker=person(world,C.ochre);worker.root.position.set(-.72,.07,.1);worker.root.rotation.y=.52;
  const scale=group(world,.85,.1,.32);
  mesh(scale,roundBox(1.03,.18,.86,.07),mat(C.green),0,.1,0);
  mesh(scale,roundBox(.9,.065,.73,.03),mat(0xc5d1bc,{metalness:.22}),0,.22,0);
  mesh(scale,cylinder(.035,.035,.9),mat(C.dark),.28,.59,-.31);
  mesh(scale,roundBox(.72,.36,.12,.035),mat(C.green),.28,1.1,-.31);
  const screen=label(scale,'0.0 kg',.61,.25,.28,1.1,-.24);
  const sack=bag(world);const crates=group(world,1.52,.12,-.75);mesh(crates,roundBox(.65,.45,.62,.03),mat(C.lime),0,.22,0);mesh(crates,box(.45,.045,.025),mat(0x96ad75),0,.27,.326);plant(world,-1.52,-.95,.8);
  const handPosition=new THREE.Vector3(),scalePosition=new THREE.Vector3(.85,.35,.32),startPosition=new THREE.Vector3(-.18,.13,.48);
  return {scene,world,update(t){
    const c=(t%10)/10;
    worker.body.rotation.x=c<.22?Math.sin(c/.22*Math.PI)*.18:0;
    worker.head.rotation.y=.22+Math.sin(t*.55)*.14;
    worker.right.shoulder.rotation.x=-.38-Math.sin(Math.min(c/.45,1)*Math.PI)*.9;worker.right.shoulder.rotation.z=-.25;
    worker.right.elbow.rotation.x=-.35;worker.left.shoulder.rotation.x=-.25;worker.left.elbow.rotation.x=-.45;
    worker.legs[0].thigh.rotation.x=.02;worker.legs[1].thigh.rotation.x=-.03;
    world.updateMatrixWorld(true);worker.right.hand.getWorldPosition(handPosition);world.worldToLocal(handPosition);handPosition.y-=.46;
    if(c<.18){sack.position.lerpVectors(startPosition,handPosition,THREE.MathUtils.smoothstep(c,0,.18));}
    else if(c<.43){sack.position.lerpVectors(handPosition,scalePosition,THREE.MathUtils.smoothstep(c,.18,.43));sack.position.y+=Math.sin((c-.18)/.25*Math.PI)*.16;}
    else if(c<.78)sack.position.copy(scalePosition);
    else if(c<.93){sack.position.lerpVectors(scalePosition,new THREE.Vector3(1.52,.57,-.75),THREE.MathUtils.smoothstep(c,.78,.93));sack.position.y+=Math.sin((c-.78)/.15*Math.PI)*.32;}
    else sack.position.set(1.52,.57,-.75);
    sack.rotation.z=c<.43?Math.sin(t*3)*.08:0;
    const kg=c<.43||c>.8?0:Math.min(4.2,(c-.43)/.12*4.2);
    screen.update(kg.toFixed(1)+' kg');
    return c<.2?'Қапты көтеріп жатыр':c<.43?'Таразыға қойып жатыр':c<.78?'Өлшем: '+kg.toFixed(1)+' кг':'Өлшенген қалдықты бөлуде';
  }};
}
function countScene(){
  const {scene,world}=baseScene('count');
  const worker=person(world,C.blue);worker.root.position.set(-.55,.07,-.55);worker.root.rotation.y=.15;
  const table=group(world,.28,.1,.45);mesh(table,roundBox(2.5,.13,.95,.05),mat(C.cream),0,.88,0);
  for(const x of [-1,1])for(const z of [-.32,.32])mesh(table,box(.075,.84,.075),mat(C.green),x,.43,z);
  const tray=mesh(table,roundBox(.65,.06,.62,.04),mat(C.lime),.81,.98,0);
  const objects=[];
  for(let i=0;i<6;i++){const o=mesh(world,i%2?cylinder(.075,.075,.17):sphere(.095),mat([C.orange,C.lime,C.cream][i%3]),-.65+(i%3)*.33,1.16,.3+Math.floor(i/3)*.3);objects.push(o);}
  const board=group(worker.left.hand,0,-.02,.02);board.rotation.x=-.35;mesh(board,roundBox(.32,.42,.035,.025),mat(C.green),0,0,0);mesh(board,box(.25,.32,.014),mat(C.lime),0,0,.025);
  mesh(table,cylinder(.025,.025,.53),mat(C.green),1.02,1.17,-.35);
  mesh(table,roundBox(.74,.36,.08,.035),mat(C.green),1.02,1.55,-.35);
  const counter=label(table,'00 / 06',.65,.26,1.02,1.55,-.299);
  plant(world,-1.6,-.95,.8);
  return {scene,world,update(t){
    const c=(t%10)/10,total=Math.min(6,Math.floor(c*7)),phase=(c*7)%1;
    worker.head.rotation.x=.14+Math.sin(t*2)*.06;worker.head.rotation.y=Math.sin(t*.8)*.2;
    worker.right.shoulder.rotation.x=-.95+Math.sin(t*2.8)*.18;worker.right.shoulder.rotation.z=-.12+Math.sin(t*1.2)*.2;worker.right.elbow.rotation.x=-.5+Math.sin(t*2.8)*.16;
    worker.left.shoulder.rotation.x=-.72;worker.left.elbow.rotation.x=-.9;worker.body.rotation.y=Math.sin(t*.7)*.04;
    objects.forEach((o,i)=>{
      const processed=i<total;const active=i===total&&total<6;
      let p=processed?1:active?THREE.MathUtils.smoothstep(phase,.1,.9):0;
      const sx=-.65+(i%3)*.33,sz=.3+Math.floor(i/3)*.3;
      o.position.set(THREE.MathUtils.lerp(sx,.93+(i%2)*.16,p),1.16+Math.sin(p*Math.PI)*.13+Math.floor(i/2)*.025*p,THREE.MathUtils.lerp(sz,.27+Math.floor(i/2)*.16,p));
      o.rotation.z=p*Math.PI*.5;
    });
    counter.update(String(total).padStart(2,'0')+' / 06');
    return total<6?`${total+1}-зат: сұрыптап, санап жатыр`:'6 зат тіркелді · келесі топтама';
  }};
}

function chartLights(){
  const scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xfffcf3,0x8ca183,2.8));
  const sun=new THREE.DirectionalLight(0xfff7e8,3.2);sun.position.set(-3,6,5);scene.add(sun);
  const edge=new THREE.DirectionalLight(0xcfe4d2,1.3);edge.position.set(3,3,-4);scene.add(edge);
  const world=group(scene);return {scene,world};
}
function barsScene(data){
  const {scene,world}=chartLights();const maximum=Math.max(1,...data.map(d=>d.value));const top=Math.ceil(maximum/20)*20;
  const hits=[],bars=[],labels=[];const n=data.length,span=5.3,barWidth=Math.min(.42,span/Math.max(n,1)*.65);
  mesh(world,roundBox(6.1,.07,1.48,.025),mat(0xf1f4e9),0,-.05,.05);
  for(let i=0;i<=4;i++){
    const y=i*.48;mesh(world,box(5.9,.008,.012),mat(0xe1e9d7),0,y,-.53);
    const tick=label(world,String(Math.round(top*i/4)),.36,.15,-3.08,y,-.5,'#91a47b','#ffffff00');labels.push(tick.object);
  }
  data.forEach((d,i)=>{
    const x=n===1?0:-span/2+i*span/(n-1),height=Math.max(.005,d.value/top*1.92);
    const material=mat(i%2?0x759d5e:0x3d7954,{roughness:.45});
    const bar=mesh(world,roundBox(barWidth,1,.4,.035),material,x,.5,0);bar.userData.datum=d;bar.userData.height=height;bars.push(bar);hits.push(bar);
    const number=label(world,Math.round(d.value).toLocaleString('ru-RU'),.47,.17,x,height+.16,.06,'#5a7b42','#ffffff00');labels.push(number.object);
    if(i%Math.max(1,Math.ceil(n/5))===0){const tick=label(world,d.label,.75,.17,x,-.12,.78,'#91a47b','#ffffff00');labels.push(tick.object);}
  });
  return {scene,world,hits,chart:true,update(t){
    const p=paused?1:1-Math.pow(1-Math.min(t/1.1,1),3);
    bars.forEach(b=>{const h=Math.max(.005,b.userData.height*p);b.scale.y=h;b.position.y=h/2;});
    return '';
  },face(camera){labels.forEach(o=>o.quaternion.copy(camera.quaternion));}};
}
function ringScene(data){
  const {scene,world}=chartLights();const total=data.reduce((s,d)=>s+d.value,0),hits=[];
  mesh(world,cylinder(1.7,1.7,.065),mat(0xf5f6ee),0,-.065,0);
  const values=total?data:[{label:'Дерек жоқ',value:1,color:'#e0e8d5'}];let angle=Math.PI*.5;
  values.forEach(d=>{
    const end=angle+d.value/(total||1)*Math.PI*2;
    const shape=new THREE.Shape();shape.absarc(0,0,1.42,angle,end,false);shape.lineTo(Math.cos(end)*.94,Math.sin(end)*.94);shape.absarc(0,0,.94,end,angle,true);shape.closePath();
    const geo=new THREE.ExtrudeGeometry(shape,{depth:.27,bevelEnabled:true,bevelSize:.018,bevelThickness:.018,bevelSegments:2,steps:1,curveSegments:36});geo.rotateX(-Math.PI/2);
    const sector=mesh(world,geo,mat(d.color,{roughness:.43,metalness:.07}),0,.05,0);sector.userData.datum={...d,value:total?d.value:0,percent:total?d.value/total*100:0};if(total)hits.push(sector);angle=end;
  });
  return {scene,world,hits,chart:true,update(t){world.rotation.y=paused?0:(1-Math.min(t/1.2,1))*.18;return '';}};
}

// A genuine mesh-projection renderer keeps the animated models usable if WebGL2
// is unavailable (for example, a remote desktop with GPU acceleration disabled).
function softwareRenderer(canvas){
  const ctx=canvas.getContext('2d',{alpha:true});if(!ctx)throw new Error('Canvas unavailable');let width=1,height=1;
  const vertex=new THREE.Vector3(),normal=new THREE.Vector3(),sun=new THREE.Vector3(-.3,.8,.65).normalize();
  function setSize(w,h){width=w;height=h;canvas.width=Math.round(w*Math.min(devicePixelRatio,1.5));canvas.height=Math.round(h*Math.min(devicePixelRatio,1.5));ctx.setTransform(canvas.width/w,0,0,canvas.height/h,0,0);}
  function render(scene,camera){
    scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);const faces=[];
    scene.traverseVisible(object=>{
      if(!object.isMesh)return;const geo=object.geometry,m=object.material;if(!geo?.attributes.position||Array.isArray(m))return;
      const pos=geo.attributes.position,index=geo.index,uv=geo.attributes.uv,count=index?index.count:pos.count;
      const points=[];
      for(let i=0;i<pos.count;i++){vertex.fromBufferAttribute(pos,i).applyMatrix4(object.matrixWorld).project(camera);points.push([(vertex.x*.5+.5)*width,(-vertex.y*.5+.5)*height,vertex.z]);}
      if(m.map?.image?.getContext){
        const corners=[points[0],points[1],points[2],points[3]];if(corners.length===4)faces.push({z:corners.reduce((s,p)=>s+p[2],0)/4,image:m.map.image,corners});return;
      }
      const color=m.color||new THREE.Color(0xffffff);normal.set(0,1,0).transformDirection(object.matrixWorld);
      for(let k=0;k<count;k+=3){const ids=[0,1,2].map(j=>index?index.getX(k+j):k+j),p=ids.map(i=>points[i]);
        const area=(p[1][0]-p[0][0])*(p[2][1]-p[0][1])-(p[1][1]-p[0][1])*(p[2][0]-p[0][0]);if(area>=0&&m.side!==THREE.DoubleSide)continue;
        if(geo.attributes.normal){normal.fromBufferAttribute(geo.attributes.normal,ids[0]).transformDirection(object.matrixWorld);}
        const light=.64+Math.max(0,normal.dot(sun))*.42;const col=color.clone().multiplyScalar(light).convertLinearToSRGB();
        faces.push({p,z:(p[0][2]+p[1][2]+p[2][2])/3,color:`rgb(${Math.min(255,Math.round(col.r*255))},${Math.min(255,Math.round(col.g*255))},${Math.min(255,Math.round(col.b*255))})`});
      }
    });
    faces.sort((a,b)=>b.z-a.z);ctx.clearRect(0,0,width,height);
    for(const f of faces){if(f.image){const [tl,tr,bl]=f.corners;ctx.save();ctx.transform((tr[0]-tl[0])/f.image.width,(tr[1]-tl[1])/f.image.width,(bl[0]-tl[0])/f.image.height,(bl[1]-tl[1])/f.image.height,tl[0],tl[1]);ctx.drawImage(f.image,0,0);ctx.restore();continue;}ctx.beginPath();ctx.moveTo(f.p[0][0],f.p[0][1]);ctx.lineTo(f.p[1][0],f.p[1][1]);ctx.lineTo(f.p[2][0],f.p[2][1]);ctx.closePath();ctx.fillStyle=f.color;ctx.strokeStyle=f.color;ctx.lineWidth=.35;ctx.fill();ctx.stroke();}
  }
  return {setSize,render,dispose(){},isSoftware:true};
}

function mount(host){
  const kind=host.dataset.workerScene||host.dataset.chartScene;
  const chart=!!host.dataset.chartScene;
  const model=chart?(kind==='bars'?barsScene:ringScene)(JSON.parse(host.dataset.chartValues||'[]')):({clean:cleanScene,weigh:weighScene,count:countScene}[kind]||cleanScene)();
  let canvas=document.createElement('canvas'),renderer;
  const labels={clean:'Қалдық жинап жүрген 3D кейіпкер',weigh:'Қапты таразыға салып өлшейтін 3D кейіпкер',count:'Қалдықтарды санап, есепке алатын 3D кейіпкер',bars:'Қалдық динамикасының көлемді бағандық диаграммасы',ring:'Қалдық құрамының көлемді сақиналы диаграммасы'};
  try{
    if(forceSoftware)throw new Error('Software renderer selected');
    const context=canvas.getContext('webgl2',{alpha:true,antialias:true,powerPreference:'low-power',preserveDrawingBuffer:true});
    if(!context)throw new Error('WebGL2 unavailable');
    renderer=new THREE.WebGLRenderer({canvas,context,alpha:true,antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.6));renderer.setClearColor(0x000000,0);renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.12;
  }catch{
    canvas=document.createElement('canvas');renderer=softwareRenderer(canvas);
  }
  canvas.setAttribute('role','img');canvas.setAttribute('aria-label',labels[kind]+'. Камераны бұру: сол және оң жақ көрсеткі пернелер.');canvas.tabIndex=0;
  host.prepend(canvas);host.dataset.renderer=renderer.isSoftware?'software':'webgl';host.classList.add('scene-ready');
  const camera=new THREE.OrthographicCamera(-3,3,2.4,-2.4,.1,50);const target=new THREE.Vector3(0,chart?(kind==='ring'?.15:.75):1,0);
  const item={host,model,renderer,camera,t:chart?0:kind==='clean'?1.1:kind==='weigh'?5.5:3,visible:true,angle:0,dirty:true,lastStep:'',frames:0};
  function resize(){const rect=host.getBoundingClientRect();const w=Math.max(1,rect.width),h=Math.max(1,rect.height);const aspect=w/h;const extent=chart?(kind==='ring'?3.6:Math.max(3.2,6.8/aspect)):(aspect<1.2?5.2/aspect:4.2);camera.left=-extent*aspect/2;camera.right=extent*aspect/2;camera.top=extent/2;camera.bottom=-extent/2;camera.updateProjectionMatrix();renderer.setSize(w,h,false);item.dirty=true;wake();}
  const resizeObserver=new ResizeObserver(resize);resizeObserver.observe(host);
  const visibleObserver=new IntersectionObserver(([entry])=>{item.visible=entry.isIntersecting;if(item.visible){item.dirty=true;wake();}},{rootMargin:'50px'});visibleObserver.observe(host);
  let startX=null,startAngle=0;
  canvas.addEventListener('pointerdown',e=>{if(e.pointerType==='touch')return;startX=e.clientX;startAngle=item.angle;canvas.setPointerCapture(e.pointerId);canvas.classList.add('dragging');});
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
  canvas.addEventListener('pointermove',e=>{
    if(startX!==null){item.angle=THREE.MathUtils.clamp(startAngle+(e.clientX-startX)*.005,-.8,.8);item.dirty=true;wake();return;}
    if(!model.hits)return;const rect=canvas.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.intersectObjects(model.hits,false)[0],tooltip=host.querySelector('.chart-tooltip');
    model.hits.forEach(o=>o.material.emissive.setHex(hit?.object===o?0x152909:0));item.dirty=true;wake();
    if(tooltip){tooltip.hidden=!hit;if(hit){const d=hit.object.userData.datum;tooltip.textContent=`${d.label}: ${d.value.toLocaleString('ru-RU',{maximumFractionDigits:1})} кг${d.percent!==undefined?' · '+d.percent.toFixed(1)+'%':''}`;tooltip.style.left=Math.min(rect.width-160,Math.max(10,e.clientX-rect.left-70))+'px';tooltip.style.top=Math.max(8,e.clientY-rect.top-36)+'px';}}
  });
  canvas.addEventListener('pointerleave',()=>{const tooltip=host.querySelector('.chart-tooltip');if(tooltip)tooltip.hidden=true;if(model.hits){model.hits.forEach(o=>o.material.emissive.setHex(0));item.dirty=true;wake();}});
  const release=()=>{startX=null;canvas.classList.remove('dragging');};canvas.addEventListener('pointerup',release);canvas.addEventListener('lostpointercapture',release);
  canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();item.angle=THREE.MathUtils.clamp(item.angle+(e.key==='ArrowLeft'?-.12:.12),-.8,.8);item.dirty=true;wake();});
  item.paint=()=>{const azimuth=(chart?(kind==='bars'?.12:.2):.58)+item.angle;camera.position.set(Math.sin(azimuth)*8,chart?(kind==='ring'?7:4.5):5.1,Math.cos(azimuth)*8);camera.lookAt(target);const step=model.update(item.t);model.face?.(camera);const caption=host.querySelector('[data-motion-step]');if(caption&&item.lastStep!==step){caption.textContent=step;item.lastStep=step;}renderer.render(model.scene,camera);item.frames++;host.dataset.frame=String(item.frames);};
  item.dispose=()=>{resizeObserver.disconnect();visibleObserver.disconnect();const geometries=new Set(),materials=new Set(),textures=new Set();model.scene.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(o.material){for(const m of Array.isArray(o.material)?o.material:[o.material]){materials.add(m);if(m.map)textures.add(m.map);}}});geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose());renderer.dispose();renderer.forceContextLoss?.();};
  entries.set(host,item);resize();item.paint();wake();
}
function syncControls(){document.querySelectorAll('[data-motion-toggle]').forEach(button=>{button.setAttribute('aria-pressed',String(paused));button.setAttribute('aria-label',paused?'Анимацияларды жалғастыру':'Анимацияларды тоқтату');button.innerHTML=`<span aria-hidden="true">${paused?'▶':'Ⅱ'}</span> ${paused?'Жалғастыру':'Тоқтату'}`;});}
function scan(){
  for(const [host,item]of entries)if(!host.isConnected){item.dispose();entries.delete(host);}
  document.querySelectorAll('[data-worker-scene],[data-chart-scene]').forEach(host=>{if(!entries.has(host))try{mount(host);}catch{host.classList.add('scene-unavailable');const status=host.querySelector('[data-motion-step]');if(status)status.textContent='Көрініс ашылмады. Браузерді жаңартып көріңіз.';}});
  syncControls();
}
function frame(time){
  raf=0;const delta=previous?Math.min((time-previous)/1000,.06):0;previous=time;
  const due=time-lastPaint>=1000/30;
  if(due&&!document.hidden){const advance=lastPaint?Math.min((time-lastPaint)/1000,.08):0;lastPaint=time;for(const item of entries.values()){if(!item.visible)continue;const moving=!paused&&(!item.model.chart||item.t<1.3);if(moving)item.t+=advance;if(moving||item.dirty){item.paint();item.dirty=false;}}}
  if(entries.size&&!document.hidden&&[...entries.values()].some(i=>i.visible&&(i.dirty||(!paused&&(!i.model.chart||i.t<1.3)))))raf=requestAnimationFrame(frame);
}
function wake(){if(!raf&&entries.size&&!document.hidden){previous=performance.now();raf=requestAnimationFrame(frame);}}
document.addEventListener('click',e=>{if(!e.target.closest('[data-motion-toggle]'))return;paused=!paused;syncControls();entries.forEach(item=>item.dirty=true);wake();});
document.addEventListener('visibilitychange',()=>{previous=0;wake();});
document.addEventListener('qaldyq:language',()=>{for(const item of entries.values()){item.model.scene.traverse(object=>object.userData.refreshLanguage?.());item.dirty=true;}wake();});
reduceMotion.addEventListener('change',()=>{paused=reduceMotion.matches;syncControls();entries.forEach(item=>item.dirty=true);wake();});
let scheduled=false;
new MutationObserver(records=>{
  if(!records.some(r=>[...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&(n.matches?.('[data-worker-scene],[data-chart-scene]')||n.querySelector?.('[data-worker-scene],[data-chart-scene]')))))return;
  if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;scan();});
}).observe(document.getElementById('app'),{childList:true,subtree:true});
scan();
