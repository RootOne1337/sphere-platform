import type {TeachingInput} from './teachingContacts';

export type WalkStage='source_gap'|'jpeg'|'http'|'decision_expired'|'neutral_wait'|'input_open'|'input_ready'|'input_command'|'input_failure'|'camera_command'|'camera_result'|'long_task'|'stop';
export type WalkStageSample={stage:WalkStage;elapsedMs:number;durationMs?:number;sequence?:number;ageMs?:number;reason?:string};

/** Local, bounded scalar trace; never a source of input authority. */
export class WalkRunDiagnostics {
  private rows:WalkStageSample[]=[];
  constructor(private began:number){}
  add(stage:WalkStage,now:number,extra:Omit<WalkStageSample,'stage'|'elapsedMs'>={}) {
    if(!Number.isFinite(now)||now<this.began)return;
    if(this.rows.length>=256)this.rows.shift();
    this.rows.push({stage,elapsedMs:now-this.began,...extra});
  }
  snapshot(){return this.rows.map(row=>({...row}));}
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
        lastDistancePx=Math.abs(event.x-down.x);lastDurationMs=Math.max(0,event.at_ms-down.at_ms);
      }
    }
  }
  return {strokesSubmitted:camera.filter(e=>e.stage==='submitted'&&e.action===0).length,strokesApplied,
    movesApplied:camera.filter(e=>e.stage==='receipt'&&e.action===2&&e.outcome==='applied').length,
    lastDistancePx,lastDurationMs};
}
