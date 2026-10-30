import {walkTargetCamera} from './walkPilot';
import {horizontalCameraTurn,verticalCameraTurn} from './walkCamera';
type Axis='x'|'y';
type View={rotation:number[];target:unknown;sequence:number;capturedAt:number;now:number;canStroke:boolean;alignmentRequired?:boolean;referenceView?:boolean};
export type CameraDragStep={hold:boolean;fraction:number|null;verticalFraction?:number|null;action?:'down'|'move'|'up';reason:string;yaw:number|null;pitch?:number|null;failed:boolean};
type Command={action:'down'|'move'|'up';axis:Axis;rotation:number[];from:number;to:number;sentAt:number;ackAt:number|null;yaw:number;pitch?:number;sequence:number;oppositeAt?:number};

/** One held finger, one fresh edge, one observed response. Never a timed macro. */
export class WalkCameraDrag {
  generation=0;
  private gain:number|null=null;
  private pitchGain:number|null=null;
  private command:Command|null=null;
  private held=false;
  private offset=0;
  private offsetY=0;
  private terminal:string|null=null;
  private began:number|null=null;
  private releasedAt=-Infinity;
  private minDelta=.012;
  private quiet=0;
  private attempts=0;
  private moves=0;
  private recenters=0;
  private bounds={min:-.25,max:.25,minY:-.25,maxY:.25};
  private feedback:{sequence:number;fraction:number;turnRadians:number;yawBefore:number;yawAfter:number;pitchBefore?:number;pitchAfter?:number;afterUpMs:number;axis?:Axis}[]=[];
  setBounds(bounds:{min:number;max:number;minY?:number;maxY?:number}){
    const b={minY:-.25,maxY:.25,...bounds};
    if(Object.values(b).some(v=>!Number.isFinite(v))||b.min<-.25||b.max>.25||b.min>0||b.max<0||b.minY<-.25||b.maxY>.25||b.minY>0||b.maxY<0)throw Error('walk_camera_bounds');
    this.bounds=b;
  }
  snapshot(){return {mode:'continuous_drag_v1',gainRadiansPerShortSide:this.gain,pulses:this.moves,
    calibrationAttempts:this.attempts,terminal:this.terminal,minimumFraction:this.minDelta,
    quietResponses:this.quiet,pitchGainRadiansPerShortSide:this.pitchGain,feedback:this.feedback.map(row=>({...row}))};}
  private stop(reason:string):CameraDragStep{this.terminal=reason;return {hold:true,fraction:null,reason,yaw:null,failed:true};}
  finishStroke(applied:boolean,at:number){
    const c=this.command;if(!c)return;
    if(!applied){this.terminal='walk_camera_input_unconfirmed';return;}
    c.ackAt=at;
    if(c.action==='down')this.held=true;
    if(c.action==='move'){if(c.axis==='y')this.offsetY=c.to;else this.offset=c.to;}
    if(c.action==='up'){this.held=false;this.offset=this.offsetY=0;this.releasedAt=at;}
  }
  cancelUnsentStroke(){
    if(!this.command||this.command.ackAt!==null)return;
    if(this.command.action==='move'){this.moves--;if((this.command.axis==='y'?this.pitchGain:this.gain)===null)this.attempts--;}
    this.command=null;
  }
  pause(now:number):CameraDragStep{
    if(this.command&&this.command.ackAt!==null)this.command=null;
    if(this.command)return {hold:true,fraction:null,reason:'walk_camera_waiting_feedback',yaw:null,failed:false};
    this.began=null;
    if(!this.held)return {hold:true,fraction:null,reason:'walk_camera_waiting_neutral',yaw:null,failed:false};
    this.command={action:'up',axis:'x',rotation:[],from:this.offset,to:0,sentAt:now,ackAt:null,yaw:0,sequence:0};
    return {hold:true,fraction:null,action:'up',reason:'walk_camera_releasing',yaw:null,failed:false};
  }
  interrupt(){this.generation++;this.command=null;this.held=false;this.offset=this.offsetY=0;this.began=null;}
  update(v:View):CameraDragStep{
    if(this.terminal)return this.stop(this.terminal);
    const target=walkTargetCamera(v.target);
    if(!target||v.rotation.length!==9||v.rotation.some(n=>!Number.isFinite(n))||v.now<v.capturedAt||v.now-v.capturedAt>250)return this.stop('walk_camera_pose_unavailable');
    const yaw=Math.atan2(target[0],target[2]);
    const pitch=Math.atan2(target[1],Math.hypot(target[0],target[2]));
    const translating=v.referenceView===true&&v.alignmentRequired!==true&&this.gain!==null&&Math.abs(yaw)<.40&&Math.abs(pitch)<.25
      &&(Math.abs(pitch)<.12||this.pitchGain!==null);
    const wait=(reason:string,hold=!translating):CameraDragStep=>({hold,fraction:null,reason,yaw,pitch,failed:false});
    if(Math.abs(pitch)>(v.referenceView?1.2:.65))return this.stop('walk_camera_pitch_mismatch');
    if(this.command){
      const c=this.command;
      if(v.now-c.sentAt>1400)return this.stop('walk_camera_feedback_timeout');
      if(c.ackAt===null||v.sequence<=c.sequence||v.capturedAt<c.ackAt+(c.action==='move'?80:40))return wait('walk_camera_waiting_feedback');
      if(c.action==='move'){
        const turn=(c.axis==='y'?verticalCameraTurn:horizontalCameraTurn)(c.rotation,v.rotation),delta=c.to-c.from;
        if(Math.abs(turn)<.002&&v.capturedAt-c.ackAt<400)return wait('walk_camera_waiting_feedback');
        if(this.feedback.length>=32)this.feedback.shift();
        this.feedback.push({sequence:v.sequence,fraction:delta,turnRadians:turn,yawBefore:c.yaw,yawAfter:yaw,
          pitchBefore:c.pitch??0,pitchAfter:pitch,afterUpMs:v.capturedAt-c.ackAt,axis:c.axis});
        if(Math.abs(turn)>.5)return this.stop('walk_camera_response_too_large');
        if(Math.abs(turn)<.002){
          if(++this.quiet>=3)return this.stop('walk_camera_response_not_observed');
          this.minDelta=Math.min(.06,Math.max(this.minDelta,Math.abs(delta)*1.4));
        }else{
          const measured=turn/delta;
          const gain=c.axis==='y'?this.pitchGain:this.gain;
          if(gain!==null&&measured*gain<0){
            // An ACK is input delivery, not the game/video response. A single
            // early opposite pose may still reflect the previous correction.
            // Hold the same command (no new MOVE/sign flip), then require an
            // independently captured second opposite response after settling.
            if(v.capturedAt-c.ackAt<400)return wait('walk_camera_waiting_feedback');
            if(Math.abs(turn)>.02){
              if(c.oppositeAt===undefined){c.oppositeAt=v.capturedAt;return wait('walk_camera_waiting_feedback');}
              if(v.capturedAt-c.oppositeAt<80)return wait('walk_camera_waiting_feedback');
              return this.stop('walk_camera_response_wrong_direction');
            }
            // Sub-degree pose noise must not reverse an already learned sign.
            this.command=null;return wait('walk_camera_waiting_feedback');
          }
          if(Math.abs(measured)<.2||Math.abs(measured)>200)return this.stop('walk_camera_gain_unqualified');
          const learned=gain===null?measured:gain*.7+measured*.3;
          if(c.axis==='y')this.pitchGain=learned;else this.gain=learned;this.quiet=0;
          // Once a held drag has crossed touch slop, small MOVE corrections
          // no longer need the larger activation distance of a new gesture.
          this.minDelta=Math.max(.002,Math.min(.012,.02/Math.abs(learned)));
        }
      }
      this.command=null;
    }
    // The server remembers an in-progress alignment through a neutral pause.
    // Its 0.08 exit threshold must remain authoritative after the local finger
    // was released; reverting to the 0.20 entry threshold deadlocked both ends.
    const engaged=v.alignmentRequired===true||this.began!==null||this.held;
    if(Math.abs(yaw)<(engaged ? .08 : .20)&&(!v.referenceView||Math.abs(pitch)<(engaged ? .06 : .12))){
      this.began=null;this.recenters=0;
      if(this.held&&v.canStroke)return this.edge(v,'up',0,yaw,'walk_camera_releasing');
      return wait(this.held?'walk_camera_waiting_neutral':'walk_camera_aligned',this.held);
    }
    if(this.began===null)this.began=v.now;
    if(v.now-this.began>8000)return this.stop('walk_camera_alignment_timeout');
    if(!v.canStroke||v.now-v.capturedAt>150)return wait('walk_camera_waiting_neutral');
    if(!this.held){
      if(v.now-this.releasedAt<120)return wait('walk_camera_recentering');
      return this.edge(v,'down',0,yaw,'walk_camera_calibrating');
    }
    if(this.moves>=120)return this.stop('walk_camera_pulse_limit');
    const axis:Axis=v.referenceView&&Math.abs(pitch)>.06&&(Math.abs(yaw)<.08||Math.abs(pitch)>Math.abs(yaw)*1.2)?'y':'x';
    const gain=axis==='y'?this.pitchGain:this.gain,error=axis==='y'?pitch:yaw,offset=axis==='y'?this.offsetY:this.offset;
    const min=axis==='y'?this.bounds.minY:this.bounds.min,max=axis==='y'?this.bounds.maxY:this.bounds.max;
    const probe=Math.max(.018,this.minDelta);
    let delta=gain===null?(offset+probe<=max?probe:-probe):Math.sign(error/gain)*Math.min(.06,Math.max(this.minDelta,Math.min(Math.abs(error)*.5,.12)/Math.abs(gain)));
    const next=Math.max(min,Math.min(max,offset+delta));delta=next-offset;
    if(Math.abs(delta)<.002){
      if(++this.recenters>4)return this.stop('walk_camera_alignment_timeout');
      return this.edge(v,'up',0,yaw,'walk_camera_recentering');
    }
    const step=this.edge(v,'move',next,yaw,gain===null?'walk_camera_calibrating':'walk_camera_turning',axis,pitch);
    if(translating&&gain!==null)step.hold=false;
    return {...step,yaw,pitch};
  }
  private edge(v:View,action:'down'|'move'|'up',to:number,yaw:number,reason:string,axis:Axis='x',pitch=0):CameraDragStep{
    if(action==='move'){this.moves++;if((axis==='y'?this.pitchGain:this.gain)===null)this.attempts=Math.min(3,this.attempts+1);}
    this.command={action,axis,rotation:[...v.rotation],from:axis==='y'?this.offsetY:this.offset,to,sentAt:v.now,ackAt:null,yaw,pitch,sequence:v.sequence};
    return {hold:true,fraction:action==='up'?null:axis==='x'?to:this.offset,
      verticalFraction:action==='up'?null:axis==='y'?to:this.offsetY,action,reason,yaw,failed:false};
  }
}
