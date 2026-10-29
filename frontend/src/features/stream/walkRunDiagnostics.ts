import type {TeachingInput} from './teachingContacts';

export type WalkStage='source_gap'|'jpeg'|'http'|'decision_expired'|'input_open'|'input_ready'|'input_command'|'input_failure'|'long_task'|'stop';
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
