/** Interpolate an already admitted command between perception replies.
 * The original reply deadline is never extended by a timer tick. No pose,
 * route progress or pedal state is predicted here. Native ACK/source guards
 * remain owned by TeachingContacts; identical points produce no new edge. */
export class PilotCommandLoop<T> {
  private target:{value:T;notAfter:number}|null=null;
  private closed=false;
  private timer:ReturnType<typeof setInterval>|null=null;
  constructor(private options:{maxHoldMs:number;ready:()=>boolean;fresh:()=>boolean;
    apply:(value:T,now:number,notAfter:number)=>void;neutral:()=>void;failure:(error:unknown)=>void}){}
  update(value:T,notAfter:number){
    const now=performance.now();
    if(this.closed||!Number.isFinite(notAfter)||notAfter<=now||notAfter-now>this.options.maxHoldMs)throw Error('pilot_command_expired');
    this.target={value,notAfter};
    if(this.timer===null)this.timer=setInterval(()=>{try{this.tick();}catch(error){this.retire(error);}},20);
    try{this.tick();}catch(error){this.retire(error);throw error;}
  }
  private tick(){
    const target=this.target;if(!target||this.closed)return;
    const now=performance.now();
    if(now>=target.notAfter||!this.options.ready()||!this.options.fresh()){this.pause();return;}
    this.options.apply(target.value,now,target.notAfter);
  }
  private cancel(){this.target=null;if(this.timer!==null)clearInterval(this.timer);this.timer=null;}
  private retire(error:unknown){
    this.closed=true;this.cancel();
    // Native owner closure must still be requested when a failed neutral
    // cannot be delivered. Never leave a timer retrying the old target.
    try{this.options.neutral();}catch{/* failure() retires the native owner. */}
    this.options.failure(error);
  }
  pause(){this.cancel();this.options.neutral();}
  close(){this.closed=true;this.cancel();}
}
