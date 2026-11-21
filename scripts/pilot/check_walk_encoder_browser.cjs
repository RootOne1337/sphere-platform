// Isolated Playwright CLI fixture. No account, emulator, user tab or input.
const fs=require('fs'),path=require('path'),http=require('http'),crypto=require('crypto'),{spawn}=require('child_process');
const root=path.resolve(__dirname,'../..'),output=path.resolve(process.argv[2]||''),cli=process.argv[3];
if(!output.startsWith(path.join(root,'.local-pilot')+path.sep)||fs.existsSync(output)||!cli||!fs.existsSync(cli))throw Error('encoder_bench_scope');
fs.mkdirSync(output);const token=crypto.randomBytes(16).toString('hex'),ts=require(path.join(root,'frontend/node_modules/typescript'));
const source=fs.readFileSync(path.join(root,'frontend/src/features/stream/walkFrameEncoder.ts'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const page=`<!doctype html><meta charset="utf-8"><style>body{font:20px Segoe UI;background:#091321;color:#edf5ff;padding:25px}video{width:800px;display:block}pre{white-space:pre-wrap;font-size:16px}</style><h1>Isolated encoder fixture · no Android input</h1><video muted autoplay playsinline></video><pre id="status">Running…</pre><script src="/encoder.js"></script><script>
(async()=>{
 const original=window.VideoFrame,canvas=document.createElement('canvas');canvas.width=1920;canvas.height=1080;
 const context=canvas.getContext('2d'),video=document.querySelector('video');let index=0,running=true;
 function draw(){if(!running)return;context.fillStyle='#173147';context.fillRect(0,0,1920,1080);
  for(let y=0;y<1080;y+=60)for(let x=0;x<1920;x+=60){context.fillStyle=((x+y+index*3)%240)<120?'#56d0cb':'#e9b75b';context.fillRect(x,y,30,30);}
  context.fillStyle='white';context.font='40px sans-serif';context.fillText('FRAME '+index++,80,80);requestAnimationFrame(draw);}
 draw();const stream=canvas.captureStream(30);video.srcObject=stream;await video.play();
 const next=()=>new Promise(resolve=>video.requestVideoFrameCallback(resolve));await next();
 const fallback=document.createElement('canvas');fallback.width=960;fallback.height=540;const cases=[];
 for(const mode of ['bitmap','video_frame']){
  window.VideoFrame=mode==='bitmap'?undefined:original;
  const encoder=new WalkFrameEncoder(),rows=[];
  try{for(let i=0;i<60;i++){await next();const at=performance.now();const encoded=await encoder.encode(video,fallback);
   rows.push({elapsedMs:performance.now()-at,bytes:encoded.blob.size,...encoder.snapshot()});}}
  finally{encoder.close();}
  const percentile=(key,p)=>{const values=rows.map(r=>r[key]).sort((a,b)=>a-b);return values[Math.floor((values.length-1)*p)];};
  cases.push({mode,samples:rows.length,totalMs:{p50:percentile('elapsedMs',.5),p95:percentile('elapsedMs',.95),maximum:percentile('elapsedMs',1)},captureMs:{p50:percentile('captureMs',.5),p95:percentile('captureMs',.95)},rows});
 }
 window.VideoFrame=original;running=false;stream.getTracks().forEach(track=>track.stop());video.srcObject=null;
 const result={schema:'sphere-walk-encoder-browser-v1',physicalActions:0,source:'synthetic_canvas_stream_1920x1080_30fps',realWebRTC:false,userTab:false,cases};
 await fetch('/result',{method:'POST',headers:{'X-Bench-Token':'${token}'},body:JSON.stringify(result)});
 document.querySelector('#status').textContent=JSON.stringify(cases.map(({rows,...summary})=>summary),null,2);document.body.dataset.state='complete';
})().catch(async error=>{await fetch('/result',{method:'POST',headers:{'X-Bench-Token':'${token}'},body:JSON.stringify({error:String(error)})});document.querySelector('#status').textContent=String(error);document.body.dataset.state='complete';});
</script>`;
const server=http.createServer((req,res)=>{
 if(req.method==='GET'&&req.url==='/'){res.setHeader('Content-Type','text/html');return res.end(page);}
 if(req.method==='GET'&&req.url==='/encoder.js'){res.setHeader('Content-Type','application/javascript');return res.end('const exports={};'+compiled+';window.WalkFrameEncoder=exports.WalkFrameEncoder;');}
 if(req.method==='GET'&&req.url==='/walk-frame-encoder.js'){res.setHeader('Content-Type','application/javascript');return res.end(fs.readFileSync(path.join(root,'frontend/public/walk-frame-encoder.js')));}
 if(req.method==='POST'&&req.url==='/result'&&req.headers['x-bench-token']===token){let body='';req.on('data',data=>{body+=data;if(body.length>65536)req.destroy();});req.on('end',()=>{try{const value=JSON.parse(body);fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(value,null,2),{flag:'wx'});res.end('saved');}catch{res.statusCode=400;res.end();}});return;}
 res.statusCode=404;res.end();
});
server.listen(0,'127.0.0.1',()=>{
 const child=spawn(process.execPath,[cli,'screenshot','--browser','chromium','--viewport-size','1280,960','--wait-for-selector','[data-state="complete"]','--timeout','60000',`http://127.0.0.1:${server.address().port}/`,path.join(output,'fixture.png')],{windowsHide:true,stdio:'inherit'});
 const timeout=setTimeout(()=>child.kill(),75000);
 child.on('exit',code=>{clearTimeout(timeout);server.close();process.exitCode=code||0;const file=path.join(output,'result.json');if(!fs.existsSync(file)||JSON.parse(fs.readFileSync(file)).error)process.exitCode=1;});
});
