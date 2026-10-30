/** Synthetic dead-zone diagnostic of the real pure servo. No browser/Android. */
const fs=require('fs'),path=require('path'),crypto=require('crypto'),cp=require('child_process');
const root=process.cwd(),ts=require(path.join(root,'frontend/node_modules/typescript'));
const folder=path.join(root,'frontend/src/features/stream');
const output=process.argv[2];
if(!output||!path.resolve(output).startsWith(path.join(root,'.local-pilot')+path.sep)||fs.existsSync(output))throw Error('diagnostic_output_scope');
const revision='5f78eb4d',oldSource=cp.execFileSync('git',['show',`${revision}:frontend/src/features/stream/walkCamera.ts`],{encoding:'utf8'});
const currentSource=fs.readFileSync(path.join(folder,'walkCamera.ts'),'utf8');
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
function load(source){
  const cache=new Map();
  const compile=(name,text)=>{
    if(cache.has(name))return cache.get(name).exports;
    const module={exports:{}};cache.set(name,module);
    const code=ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
    new Function('require','module','exports',code)(specifier=>{
      if(!specifier.startsWith('.'))throw Error('unexpected_dependency');
      const target=path.resolve(path.dirname(name),specifier+'.ts');
      if(!target.startsWith(folder+path.sep))throw Error('dependency_scope');
      return compile(target,fs.readFileSync(target,'utf8'));
    },module,module.exports);return module.exports;
  };
  return compile(path.join(folder,'walkCamera.ts'),source).WalkCameraServo;
}
const rotation=y=>[Math.cos(y),0,-Math.sin(y),0,1,0,Math.sin(y),0,Math.cos(y)];
function trial(Servo,{shortSide,slopPx,gain,goal},duration){
  const servo=new Servo();let heading=0,last=null,sequence=0,pulses=[];
  for(let now=1000;now<=10000;now+=100){
    const yaw=goal-heading;
    last=servo.update({rotation:rotation(heading),target:[Math.sin(yaw),0,Math.cos(yaw)],sequence:++sequence,capturedAt:now,now,canStroke:true});
    if(last.fraction!==null){
      const pixels=Math.round(last.fraction*shortSide);
      const effect=Math.sign(pixels)*gain*Math.max(0,Math.abs(pixels)-slopPx)/shortSide;
      heading+=effect;servo.finishStroke(true,now+duration);
      pulses.push({pixels,effectRadians:effect,durationMs:duration});
    }
    if(last.failed||!last.hold)break;
  }
  return {aligned:!last.failed&&!last.hold,reason:last.reason,errorRadians:goal-heading,pulses,summary:servo.snapshot()};
}
const baseline=load(oldSource),candidate=load(currentSource),cases=[];
for(const shortSide of [540,1080])for(const slopPx of [8,12,16])for(const gain of [-12,12])for(const goal of [-.6,.6,1.2]){
  const parameters={shortSide,slopPx,gain,goal};cases.push({parameters,baseline:trial(baseline,parameters,30),candidate:trial(candidate,parameters,130)});
}
const unsupported=trial(candidate,{shortSide:540,slopPx:40,gain:12,goal:1.2},130);
const result={schema:'sphere-camera-deadzone-simulation-v1',baselineRevision:revision,baselineSha256:sha(oldSource),candidateSha256:sha(currentSource),physicalActions:0,liveGame:false,syntheticDeadZone:true,realPureServo:true,nativeDurationIsModel:true,
  baselineAligned:cases.filter(c=>c.baseline.aligned).length,candidateAligned:cases.filter(c=>c.candidate.aligned).length,total:cases.length,cases,unsupported};
fs.writeFileSync(output,JSON.stringify(result,null,2),{flag:'wx'});
process.stdout.write(JSON.stringify({baselineAligned:result.baselineAligned,candidateAligned:result.candidateAligned,total:result.total,unsupportedReason:unsupported.reason})+'\n');
