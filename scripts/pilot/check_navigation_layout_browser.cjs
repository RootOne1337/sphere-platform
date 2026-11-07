// Actual map/context React components, isolated local fixture, no device input.
const fs=require('fs'),path=require('path'),http=require('http'),crypto=require('crypto'),{spawnSync,spawn}=require('child_process');
const root=path.resolve(__dirname,'../..'),front=path.join(root,'frontend'),ts=require(path.join(front,'node_modules/typescript'));
const out=path.resolve(process.argv[2]||''),cli=process.argv[3],geometry=path.resolve(process.argv[4]||''),frame=path.resolve(process.argv[5]||'');
const inside=p=>p.startsWith(path.join(root,'.local-pilot')+path.sep);
if(!inside(out)||fs.existsSync(out)||!inside(geometry)||!inside(frame)||!cli||[geometry,frame].some(p=>!fs.existsSync(p)||fs.statSync(p).size>4*1024**2))throw Error('fixture_scope');
fs.mkdirSync(out);const token=crypto.randomBytes(16).toString('hex'),raw=fs.readFileSync(geometry),data=JSON.parse(raw);
const definitions=new Map(),sources={};
const libraries={'react':'react/cjs/react.production.js','react/jsx-runtime':'react/cjs/react-jsx-runtime.production.js',
 'react-dom':'react-dom/cjs/react-dom.production.js','react-dom/client':'react-dom/cjs/react-dom-client.production.js','scheduler':'scheduler/cjs/scheduler.production.js'};
const mocks={
 reconstructionClient:`exports.reconstructionRequest=async p=>p.endsWith('geometry-alternatives')?{json:async()=>({alternatives:[]})}:{arrayBuffer:async()=>window.fixtureRaw.buffer};`,
 RecordedRouteFrame:`const React=require('react');exports.RecordedRouteFrame=()=>React.createElement('div',null,React.createElement('p',null,'Исходная запись · фикстура верстки'),React.createElement('img',{'data-source-frame':'',src:'/frame.jpg',style:{width:'100%'}}));`,
};
function compile(id){
 if(definitions.has(id))return;definitions.set(id,null);let code,deps={};
 if(libraries[id])code=fs.readFileSync(path.join(front,'node_modules',libraries[id]),'utf8');
 else if(mocks[id])code=mocks[id];
 else{
  const file=path.join(front,'src/features/stream',id),source=fs.readFileSync(file,'utf8');sources[id]=crypto.createHash('sha256').update(source).digest('hex');
  code=ts.transpileModule(source,{fileName:file,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 }
 for(const match of code.matchAll(/require\(["']([^"']+)["']\)/g)){
  const name=match[1];let resolved=name;
  if(name.startsWith('./')){const base=name.slice(2);resolved=mocks[base]?base:fs.existsSync(path.join(front,'src/features/stream',base+'.tsx'))?base+'.tsx':base+'.ts';}
  if(!libraries[resolved]&&!mocks[resolved]&&!/^[\w-]+\.tsx?$/.test(resolved))throw Error('unknown_fixture_import:'+resolved);
  deps[name]=resolved;compile(resolved);
 }
 definitions.set(id,{code,deps});
}
compile('NavigationRouteContext.tsx');compile('react-dom/client');
const modules=[...definitions].map(([id,v])=>JSON.stringify(id)+':[function(require,module,exports){'+v.code+'\n},'+JSON.stringify(v.deps)+']').join(',');
const bundle=`window.process={env:{NODE_ENV:'production'}};const defs={${modules}},cache={};function req(id){if(cache[id])return cache[id].exports;const m={exports:{}};cache[id]=m;const [fn,deps]=defs[id];fn(n=>req(deps[n]),m,m.exports);return m.exports;}window.React=req('react');window.ReactDOM=req('react-dom/client');window.NavigationRouteContext=req('NavigationRouteContext.tsx').NavigationRouteContext;`;
const css=path.join(out,'style.css'),tailwind=spawnSync(process.execPath,[path.join(front,'node_modules/tailwindcss/lib/cli.js'),'-c',path.join(front,'tailwind.config.ts'),'--content',path.join(front,'src/features/stream/NavigationRouteContext.tsx')+','+path.join(front,'src/features/stream/RouteGeometryMap.tsx'),'-i',path.join(front,'app/globals.css'),'-o',css,'--minify'],{cwd:front,windowsHide:true,encoding:'utf8'});
if(tailwind.status!==0)throw Error('fixture_css:'+tailwind.stderr);
const page=`<!doctype html><html class="dark"><meta charset="utf-8"><link rel="stylesheet" href="/style.css"><style>body{margin:20px;background:#081321;color:#e6f0ff;font:14px Segoe UI}h1{font-size:22px;margin-bottom:14px}</style><h1>Проверка устойчивости верстки · реальные компоненты · игровой ввод отключён</h1><div id="root"></div><script src="/bundle.js"></script><script>
(async()=>{window.fixtureRaw=new Uint8Array(await(await fetch('/geometry.json')).arrayBuffer());const map=JSON.parse(new TextDecoder().decode(fixtureRaw)),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',fixtureRaw)),n=>n.toString(16).padStart(2,'0')).join('');
 const React=window.React,camera=map.cameras[0],r=camera.camera_to_world,rotation=[0,1,2].flatMap(i=>[0,1,2].map(j=>r[j][i]));
 const source={clip:'d'.repeat(32),scope:'e'.repeat(32),manifestSha:map.source_manifest_sha256,folder:{},rows:map.cameras.map(c=>({relative_ticks_90k:c.ticks_90k}))};
 let update;const App=()=>{const [observation,set]=React.useState(null);update=set;return React.createElement(NavigationRouteContext,{job:{id:'a'.repeat(32),key:'b'.repeat(64)},source,assetsReady:true,busy:true,preparedLandmarks:4096,observation,comparison:React.createElement('div',null,React.createElement('p',null,'Сравнение · фикстура без живого управления'),React.createElement('img',{src:'/frame.jpg',style:{width:'100%'}}))});};
 ReactDOM.createRoot(document.querySelector('#root')).render(React.createElement(App));
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));for(let i=0;i<100&&!document.querySelector('svg[aria-label="Проекция опорных точек и положений камеры"]');i++)await sleep(20);
 const poses=[];const measure=state=>{const boxes={};for(const label of ['Состояние локализации','Состояние живого маркера','Проекция опорных точек и положений камеры']){const r=document.querySelector('[aria-label="'+label+'"]').getBoundingClientRect();boxes[label]={top:r.top,height:r.height};}poses.push({state,boxes});};
 const capturedAt=performance.now(),reply={id:'layout',captureEpoch:'layout-epoch',geometrySha256:sha,referenceTicks90k:camera.ticks_90k,sequence:1,jpegSha256:'f'.repeat(64),computeMs:10,method:'fixture',physicalActions:0,executionQualified:false,groundRoute:false,pose:{state:'localized',reason:'verified',inliers:57,segment:0,progress_units:0,polyline_px:[],center:camera.center,rotation}};
 update({reply,capturedAt,answeredAt:capturedAt+10});await sleep(80);measure('fresh');await sleep(300);measure('recent');await sleep(800);measure('expired');
 update({reply:{...reply,pose:{...reply.pose,state:'unknown',inliers:0,center:null,rotation:null}},capturedAt:performance.now(),answeredAt:performance.now()});await sleep(50);measure('unknown');
 const shifts=poses.slice(1).map(p=>Math.max(...Object.keys(p.boxes).map(k=>Math.abs(p.boxes[k].top-poses[0].boxes[k].top))));
 const result={schema:'sphere-navigation-layout-browser-v1',physicalActions:0,realLiveLocalization:false,sourceCameras:map.cameras.length,sourcePoints:map.points.length,viewport:[innerWidth,innerHeight],poses,maximumShiftPx:Math.max(...shifts),passed:Math.max(...shifts)<.5};
 await fetch('/result',{method:'POST',headers:{'X-Fixture-Token':'${token}'},body:JSON.stringify(result)});document.body.dataset.state='complete';
})().catch(async error=>{await fetch('/result',{method:'POST',headers:{'X-Fixture-Token':'${token}'},body:JSON.stringify({error:String(error)})});document.body.dataset.state='complete';});
</script></html>`;
const server=http.createServer((req,res)=>{
 if(req.method==='GET'){
  const values={'/':['text/html',page],'/bundle.js':['application/javascript',bundle],'/style.css':['text/css',fs.readFileSync(css)],'/geometry.json':['application/json',raw],'/frame.jpg':['image/jpeg',fs.readFileSync(frame)]};
  if(values[req.url]){res.setHeader('Content-Type',values[req.url][0]);return res.end(values[req.url][1]);}
 }
 if(req.method==='POST'&&req.url==='/result'&&req.headers['x-fixture-token']===token){let body='';req.on('data',c=>{body+=c;if(body.length>32000)req.destroy();});req.on('end',()=>{const v=JSON.parse(body);fs.writeFileSync(path.join(out,'result-'+(v.viewport?.[0]||'error')+'.json'),JSON.stringify(v,null,2),{flag:'wx'});res.end('saved');});return;}
 res.writeHead(404);res.end();
});
server.listen(0,'127.0.0.1',async()=>{
 try{for(const width of [1880,760])await new Promise((resolve,reject)=>{const child=spawn(process.execPath,[cli,'screenshot','--browser','chromium','--viewport-size',width+',1250','--full-page','--wait-for-selector','[data-state="complete"]','--timeout','15000',`http://127.0.0.1:${server.address().port}/`,path.join(out,'layout-'+width+'.png')],{windowsHide:true,stdio:'inherit'});child.on('exit',c=>c?reject(Error('browser_failed')):resolve());});
  for(const width of [1880,760]){const p=path.join(out,'result-'+width+'.json');if(!fs.existsSync(p)||!JSON.parse(fs.readFileSync(p)).passed)throw Error('layout_failed');}
  fs.writeFileSync(path.join(out,'source-hashes.json'),JSON.stringify(sources,null,2));
 }catch(error){console.error(String(error));process.exitCode=1;}finally{server.close();}
});
