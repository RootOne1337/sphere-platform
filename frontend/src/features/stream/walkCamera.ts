import {walkTargetCamera} from './walkPilot';

type View={rotation:number[];target:unknown;sequence:number;capturedAt:number;now:number;canStroke:boolean};
export type CameraStep={hold:boolean;fraction:number|null;reason:string;yaw:number|null;failed:boolean};
type Stroke={rotation:number[];fraction:number;yaw:number;sentAt:number;endedAt:number|null};
const dot=(a:number[],b:number[])=>a.reduce((sum,n,i)=>sum+n*b[i],0);
export function horizontalCameraTurn(before:number[],after:number[]):number {
  const right=before.slice(0,3),forward=before.slice(6,9),next=after.slice(6,9);
  return Math.atan2(dot(right,next),dot(forward,next));
}
export function verticalCameraTurn(before:number[],after:number[]):number {
  return Math.atan2(dot(before.slice(3,6),after.slice(6,9)),dot(before.slice(6,9),after.slice(6,9)));
}

/** Tiny horizontal pulses, followed by NEW localized RGB feedback. No pitch input. */
export class WalkCameraServo {
  private gain:number|null=null;
  private stroke:Stroke|null=null;
  private terminal:string|null=null;
  private attempts=0;
  private lastSequence=0;
  private lastPulseAt=-Infinity;
  private activeSince:number|null=null;
  private badResponses=0;
  private pulses=0;
  private minimumFraction=.012;
  private quietResponses=0;
  private feedback:{sequence:number;fraction:number;turnRadians:number;yawBefore:number;yawAfter:number;afterUpMs:number}[]=[];
  private stop(reason:string):CameraStep {this.terminal=reason;return {hold:true,fraction:null,reason,yaw:null,failed:true};}
  finishStroke(applied:boolean,at:number){
    if(!this.stroke)return;
    if(!applied)this.terminal='walk_camera_input_unconfirmed';
    else this.stroke.endedAt=at;
  }
  snapshot(){return {gainRadiansPerShortSide:this.gain,pulses:this.pulses,calibrationAttempts:this.attempts,terminal:this.terminal,
    minimumFraction:this.minimumFraction,quietResponses:this.quietResponses,feedback:this.feedback.map(row=>({...row}))};}
  cancelUnsentStroke(){
    if(!this.stroke||this.stroke.endedAt!==null)return;
    this.stroke=null;this.pulses--;if(this.gain===null)this.attempts--;
    this.lastPulseAt=-Infinity;
  }
  update(view:View):CameraStep {
    if(this.terminal)return this.stop(this.terminal);
    const target=walkTargetCamera(view.target),{now,rotation}=view;
    if(!target||rotation.length!==9||rotation.some(n=>!Number.isFinite(n))
      ||!Number.isFinite(now)||now<view.capturedAt||now-view.capturedAt>250)return this.stop('walk_camera_pose_unavailable');
    const yaw=Math.atan2(target[0],target[2]),pitch=Math.atan2(target[1],Math.hypot(target[0],target[2]));
    const wait=(reason:string):CameraStep=>({hold:true,fraction:null,reason,yaw,failed:false});
    // Vertical control needs a separate calibration. Never silently drag down
    // to repair an incompatible view or a missing ground model.
    if(Math.abs(pitch)>.65)return this.stop('walk_camera_pitch_mismatch');
    if(this.stroke){
      const s=this.stroke;
      if(now-s.sentAt>1400)return this.stop('walk_camera_feedback_timeout');
      if(s.endedAt===null||view.capturedAt<s.endedAt+150||view.sequence<=this.lastSequence)return wait('walk_camera_waiting_feedback');
      const turn=horizontalCameraTurn(s.rotation,rotation);
      if(this.feedback.length>=32)this.feedback.shift();
      this.feedback.push({sequence:view.sequence,fraction:s.fraction,turnRadians:turn,yawBefore:s.yaw,yawAfter:yaw,afterUpMs:view.capturedAt-s.endedAt});
      if(Math.abs(turn)>.4)return this.stop('walk_camera_response_too_large');
      if(Math.abs(turn)<.002){
        this.quietResponses++;
        if(this.quietResponses>=3||Math.abs(s.fraction)>=.039)return this.stop('walk_camera_response_not_observed');
        this.minimumFraction=Math.min(.04,Math.max(this.minimumFraction,Math.abs(s.fraction)*1.5));
        this.stroke=null;return wait('walk_camera_waiting_feedback');
      }
      this.quietResponses=0;
      const measured=turn/s.fraction;
      if(this.gain!==null&&measured*this.gain<=0)return this.stop('walk_camera_response_wrong_direction');
      if(Math.abs(measured)<.2||Math.abs(measured)>200)return this.stop('walk_camera_gain_unqualified');
      this.gain=this.gain===null?measured:this.gain*.75+measured*.25;
      if(Math.abs(yaw)>Math.abs(s.yaw)+.08)this.badResponses++;
      else this.badResponses=0;
      if(this.badResponses>=2)return this.stop('walk_camera_not_converging');
      this.stroke=null;
    }
    if(Math.abs(yaw)<=.14){this.activeSince=null;return {hold:false,fraction:null,reason:'walk_camera_aligned',yaw,failed:false};}
    if(this.activeSince===null)this.activeSince=now;
    if(now-this.activeSince>8000)return this.stop('walk_camera_alignment_timeout');
    if(!view.canStroke||now-view.capturedAt>70||now-this.lastPulseAt<400)return wait('walk_camera_waiting_neutral');
    if(this.pulses>=120)return this.stop('walk_camera_pulse_limit');
    let fraction:number;
    if(this.gain===null){
      if(this.attempts>=3)return this.stop('walk_camera_response_not_observed');
      this.attempts++;
      fraction=Math.max(this.minimumFraction,this.attempts===1?.018:this.attempts===2?.032:.04);
    }else {
      // At most 0.12 radians of predicted rotation and 4% of the short side.
      const desired=Math.sign(yaw/this.gain)*Math.min(Math.abs(yaw)*.6,.12)/Math.abs(this.gain);
      fraction=Math.sign(desired)*Math.min(.04,Math.max(this.minimumFraction,Math.abs(desired)));
      if(Math.abs(fraction*this.gain)>.24001)return this.stop('walk_camera_resolution_limit');
    }
    this.lastSequence=view.sequence;this.lastPulseAt=now;this.pulses++;
    this.stroke={rotation:[...rotation],fraction,yaw,sentAt:now,endedAt:null};
    return {hold:true,fraction,reason:this.gain===null?'walk_camera_calibrating':'walk_camera_turning',yaw,failed:false};
  }
}
