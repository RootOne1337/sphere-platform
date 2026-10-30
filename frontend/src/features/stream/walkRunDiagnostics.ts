import type {TeachingInput} from './teachingContacts';

export type WalkStage='source_gap'|'jpeg'|'encoder_capture'|'encoder_worker'|'encoder_jpeg'|'encoder_hash'|'http'|'decision_expired'|'neutral_wait'|'input_open'|'input_ready'|'input_command'|'input_failure'|'camera_command'|'camera_result'|'long_task'|'stop';
export type WalkStageSample={stage:WalkStage;elapsedMs:number;durationMs?:number;sequence?:number;ageMs?:number;reason?:string};

/** Local, bounded scalar trace; never a source of input authority. */
export class WalkRunDiagnostics {
  private rows:WalkStageSample[]=[];
  private totals:Record<string,{count:number;durationMs:number;maxDurationMs:number;maxAgeMs:number}>={};
  constructor(private began:number){}
  add(stage:WalkStage,now:number,extra:Omit<WalkStageSample,'stage'|'elapsedMs'>={}) {
    if(!Number.isFinite(now)||now<this.began)return;
    const total=this.totals[stage]??{count:0,durationMs:0,maxDurationMs:0,maxAgeMs:0};total.count++;
    if(extra.durationMs!==undefined&&Number.isFinite(extra.durationMs)){total.durationMs+=extra.durationMs;total.maxDurationMs=Math.max(total.maxDurationMs,extra.durationMs);}
    if(extra.ageMs!==undefined&&Number.isFinite(extra.ageMs))total.maxAgeMs=Math.max(total.maxAgeMs,extra.ageMs);
    this.totals[stage]=total;
    if(this.rows.length>=256)this.rows.shift();
    this.rows.push({stage,elapsedMs:now-this.began,...extra});
  }
  snapshot(){return this.rows.map(row=>({...row}));}
  summary(){return Object.fromEntries(Object.entries(this.totals).map(([key,value])=>[key,{...value}]));}
}

/** Keep the final failure and original counts when the scalar upload is large. */
export function boundedWalkSummary<T extends {observations:unknown[];nativeInputs:unknown[]}>(body:T):T{
  const result={...body,observations:[...body.observations],nativeInputs:[...body.nativeInputs]};
  while(new Blob([JSON.stringify(result)]).size>480*1024){
    // Do not alias an alternating success/failure stream into "all success".
    // Reduce routine following samples before any loss/confirmation/stop rows.
    let routine=0;
    const reduced=result.observations.filter((row,i,a)=>{
      const r=row as {state?:string;poseState?:string}|null;
      if(i===0||i===a.length-1||r?.state!=='following'||r.poseState!=='localized')return true;
      return routine++%2===0;
    });
    if(result.observations.length>64&&reduced.length<result.observations.length)result.observations=reduced;
    else if(result.nativeInputs.length>64)result.nativeInputs=result.nativeInputs.slice(-Math.ceil(result.nativeInputs.length/2));
    else if(result.observations.length>64){
      const key=(row:unknown)=>{const r=row as Record<string,unknown>|null;return JSON.stringify([r?.state,r?.poseState,r?.poseReason,r?.plannerReason]);};
      const transitions=result.observations.filter((row,i,a)=>i===0||i===a.length-1||i%2===0||key(row)!==key(a[i-1])||key(row)!==key(a[i+1]));
      result.observations=transitions.length<result.observations.length?transitions:result.observations.filter((_,i,a)=>i%2===0||i===a.length-1);
    }else throw Error('walk_report_quota');
  }
  return result;
}

export function walkInputSummary(events:TeachingInput[]) {
  const motion=(event:TeachingInput)=>event.pointer_id===0&&(event.action===0||event.action===2);
  return {submitted:events.filter(event=>event.stage==='submitted'&&motion(event)).length,
    applied:events.filter(event=>event.stage==='receipt'&&motion(event)&&event.outcome==='applied').length};
}

/** Contact 1 belongs to the camera in the foot pilot, not to walking motion. */
export function walkCameraInputSummary(events:TeachingInput[]) {
  const camera=events.filter(event=>event.pointer_id===1),downs=new Map<number,TeachingInput>();
  let strokesApplied=0,lastDistancePx:number|null=null,lastDurationMs:number|null=null;
  for(const event of camera){
    if(event.stage==='submitted'&&event.action===0)downs.set(event.gesture,event);
    if(event.stage==='receipt'&&event.action===1&&event.outcome==='applied'){
      strokesApplied++;const down=downs.get(event.gesture);
      if(down&&down.x!==undefined&&event.x!==undefined){
        lastDistancePx=Math.hypot(event.x-down.x,(event.y??0)-(down.y??0));lastDurationMs=Math.max(0,event.at_ms-down.at_ms);
      }
    }
  }
  return {strokesSubmitted:camera.filter(e=>e.stage==='submitted'&&e.action===0).length,strokesApplied,
    movesApplied:camera.filter(e=>e.stage==='receipt'&&e.action===2&&e.outcome==='applied').length,
    lastDistancePx,lastDurationMs};
}
