// Isolated Chromium: original H.264 remux, production encoder/worker, no input.
const fs=require('fs'),path=require('path'),http=require('http'),crypto=require('crypto'),{spawn}=require('child_process');
const root=path.resolve(__dirname,'../..'),out=path.resolve(process.argv[2]||''),cli=process.argv[3],media=path.resolve(process.argv[4]||''),loopback=process.argv[5]==='webrtc';
const inside=p=>p.startsWith(path.join(root,'.local-pilot')+path.sep);
if(!inside(out)||fs.existsSync(out)||!inside(media)||!fs.existsSync(media)||fs.statSync(media).size>256*1024**2||!cli||!fs.existsSync(cli))throw Error('bench_scope');
fs.mkdirSync(out);const token=crypto.randomBytes(16).toString('hex'),ts=require(path.join(root,'frontend/node_modules/typescript'));
const compiled=ts.transpileModule(fs.readFileSync(path.join(root,'frontend/src/features/stream/walkFrameEncoder.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const page=`<!doctype html><meta charset="utf-8"><style>body{background:#091321;color:#eaf5ff;font:18px Segoe UI;padding:20px}video{width:550px}pre{font-size:15px}</style><h1>Recorded-game encoder comparison · ${loopback?'local WebRTC loopback':'MP4 playback'} · no Android input</h1><video id="source" src="/source.mp4" muted autoplay playsinline></video>${loopback?'<video id="receiver" muted autoplay playsinline></video>':''}<pre id="status">Running…</pre><script>
const NativeWorker=window.Worker;window.Worker=class extends NativeWorker{constructor(url,options){super(String(url)+'?readback='+(window.benchReadback?'1':'0'),options);}};
</script><script src="/encoder.js"></script><script>
(async()=>{const source=document.querySelector('#source');await source.play();let video=source,peers=[],received=null;
 if(${loopback}){
  const outgoing=new RTCPeerConnection({iceServers:[]}),incoming=new RTCPeerConnection({iceServers:[]});peers=[outgoing,incoming];
  outgoing.onicecandidate=e=>{if(e.candidate)incoming.addIceCandidate(e.candidate);};incoming.onicecandidate=e=>{if(e.candidate)outgoing.addIceCandidate(e.candidate);};
  const attached=new Promise(resolve=>incoming.ontrack=e=>{received=e.receiver;video=document.querySelector('#receiver');video.srcObject=e.streams[0];resolve();});
  const stream=source.captureStream(30);for(const track of stream.getVideoTracks())outgoing.addTrack(track,stream);
  const codecs=RTCRtpSender.getCapabilities('video').codecs,preferred=codecs.filter(c=>c.mimeType==='video/H264');
  if(preferred.length)for(const transceiver of outgoing.getTransceivers())transceiver.setCodecPreferences([...preferred,...codecs.filter(c=>c.mimeType!=='video/H264')]);
  await outgoing.setLocalDescription(await outgoing.createOffer());await incoming.setRemoteDescription(outgoing.localDescription);
  await incoming.setLocalDescription(await incoming.createAnswer());await outgoing.setRemoteDescription(incoming.localDescription);await attached;await video.play();
  for(const sender of outgoing.getSenders()){const p=sender.getParameters();if(!p.encodings.length)p.encodings=[{}];p.encodings[0].maxBitrate=40000000;p.encodings[0].maxFramerate=30;p.encodings[0].scaleResolutionDownBy=1;p.degradationPreference='maintain-resolution';await sender.setParameters(p);}
 }
 const next=()=>new Promise(resolve=>video.requestVideoFrameCallback(resolve));await next();
 const canvas=document.createElement('canvas');canvas.width=960;canvas.height=540;const cases=[];
 for(const mode of ['default','frequent_readback']){window.benchReadback=mode!=='default';source.currentTime=0;await next();
  const encoder=new WalkFrameEncoder(),rows=[];
  try{for(let i=0;i<240;i++){await next();const at=performance.now(),frame=await encoder.encode(video,canvas);rows.push({ms:performance.now()-at,bytes:frame.blob.size,...encoder.snapshot()});}}
  finally{encoder.close();}
  const values=rows.map(r=>r.ms).sort((a,b)=>a-b),q=p=>values[Math.floor((values.length-1)*p)];
  cases.push({mode,samples:rows.length,p50:q(.5),p95:q(.95),p99:q(.99),maximum:q(1),over100:rows.filter(r=>r.ms>100).length,over250:rows.filter(r=>r.ms>250).length,rows});
 }
 source.pause();let transport=null;if(received){const stats=await received.getStats();for(const row of stats.values())if(row.type==='inbound-rtp'&&row.kind==='video'){const codec=stats.get(row.codecId);transport={codec:codec?.mimeType,framesDecoded:row.framesDecoded,framesDropped:row.framesDropped,totalDecodeTime:row.totalDecodeTime};}}
 const result={schema:'sphere-recorded-game-encoder-v1',physicalActions:0,originalGameVideo:true,reencoded:${loopback?'true':'false'},realWebRTC:${loopback},userTab:false,realAndroidStream:false,geometry:[video.videoWidth,video.videoHeight],transport,cases};for(const peer of peers)peer.close();
 await fetch('/result',{method:'POST',headers:{'X-Bench-Token':'${token}'},body:JSON.stringify(result)});document.querySelector('#status').textContent=JSON.stringify(cases.map(({rows,...s})=>s),null,2);document.body.dataset.state='complete';
})().catch(async error=>{await fetch('/result',{method:'POST',headers:{'X-Bench-Token':'${token}'},body:JSON.stringify({error:String(error)})});document.body.dataset.state='complete';});
</script>`;
const worker=fs.readFileSync(path.join(root,'frontend/public/walk-frame-encoder.js'),'utf8');
const server=http.createServer((req,res)=>{
 if(req.method==='GET'&&req.url==='/'){res.setHeader('Content-Type','text/html');return res.end(page);}
 if(req.method==='GET'&&req.url==='/encoder.js'){res.setHeader('Content-Type','application/javascript');return res.end('const exports={};'+compiled+';window.WalkFrameEncoder=exports.WalkFrameEncoder;');}
 if(req.method==='GET'&&req.url.startsWith('/walk-frame-encoder.js')){res.setHeader('Content-Type','application/javascript');return res.end(req.url.endsWith('=1')?worker.replace('{alpha:false}','{alpha:false,willReadFrequently:true}'):worker);}
 if(req.method==='GET'&&req.url==='/source.mp4'){
  const size=fs.statSync(media).size,match=/^bytes=(\d+)-(\d*)$/.exec(req.headers.range||'');let start=0,end=size-1;
  if(match){start=Number(match[1]);end=match[2]?Math.min(end,Number(match[2])):end;if(start>end||end>=size){res.writeHead(416);return res.end();}}
  res.writeHead(match?206:200,{'Content-Type':'video/mp4','Accept-Ranges':'bytes','Content-Length':end-start+1,...(match?{'Content-Range':`bytes ${start}-${end}/${size}`}:{})});return fs.createReadStream(media,{start,end}).pipe(res);
 }
 if(req.method==='POST'&&req.url==='/result'&&req.headers['x-bench-token']===token){let body='';req.on('data',chunk=>{body+=chunk;if(body.length>512*1024)req.destroy();});req.on('end',()=>{try{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(JSON.parse(body),null,2),{flag:'wx'});res.end('saved');}catch{res.writeHead(400);res.end();}});return;}
 res.writeHead(404);res.end();
});
server.listen(0,'127.0.0.1',()=>{
 const child=spawn(process.execPath,[cli,'screenshot','--browser','chromium','--viewport-size','1280,1100','--wait-for-selector','[data-state="complete"]','--timeout','100000',`http://127.0.0.1:${server.address().port}/`,path.join(out,'fixture.png')],{windowsHide:true,stdio:'inherit'});
 const timer=setTimeout(()=>child.kill(),110000);child.on('exit',code=>{clearTimeout(timer);server.close();process.exitCode=code||0;const p=path.join(out,'result.json');if(!fs.existsSync(p)||JSON.parse(fs.readFileSync(p)).error)process.exitCode=1;});
});
