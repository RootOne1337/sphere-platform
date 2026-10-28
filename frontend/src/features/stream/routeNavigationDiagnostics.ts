import type {NavigationReply} from './routeNavigation';

/** Bounded, opt-in export of the observed session; it grants no input authority. */
export type RouteDiagnosticSample={elapsedMs:number;sourceSequence:number;state:NavigationReply['pose']['state'];reason:string;
  inliers:number;segment:number|null;progressUnits:number|null;method:string;computeMs:number;frameToReplyMs:number;late:boolean};
const LIMIT=1200;

export class RouteNavigationDiagnostics {
  private rows:RouteDiagnosticSample[]=[];
  private omitted=0;
  constructor(private readonly jobId:string,private readonly clipId:string|null,private readonly startedAt:number) {}
  add(reply:NavigationReply,capturedAt:number,answeredAt:number):void {
    if(!Number.isFinite(capturedAt)||!Number.isFinite(answeredAt)||capturedAt<this.startedAt||answeredAt<capturedAt)return;
    const row:RouteDiagnosticSample={elapsedMs:capturedAt-this.startedAt,sourceSequence:reply.sequence,state:reply.pose.state,reason:reply.pose.reason,
      inliers:reply.pose.inliers,segment:reply.pose.segment,progressUnits:reply.pose.progress_units,method:reply.method,
      computeMs:reply.computeMs,frameToReplyMs:answeredAt-capturedAt,late:answeredAt-capturedAt>250};
    if(this.rows.length===LIMIT){this.omitted++;return;}
    this.rows.push(row);
  }
  get size(){return this.rows.length;}
  export(){
    return {schema:'sphere-route-observation-diagnostics-v1',jobId:this.jobId,clipId:this.clipId,
      scope:'manual_live_observation',physicalActions:0,executionQualified:false,groundRoute:false,
      fullAndroidLatencyKnown:false,sceneIsOperatorAssumption:true,framesIncluded:false,inputsIncluded:false,
      timing:'browser_frame_callback_to_response',samplesOmitted:this.omitted,samples:this.rows.map(row=>({...row}))};
  }
}
