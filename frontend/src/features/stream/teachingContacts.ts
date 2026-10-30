import type { DirectControlEndpoint } from './directPointerTransport';
import type { DirectVideoBinding } from './directVideoProtocol';

export type TeachingPoint = { x: number; y: number };
export type TeachingInput = { stage: 'submitted' | 'receipt' | 'closed'; at_ms: number;
  sequence: number; gesture: number; action: number; pointer_id: number; x?: number; y?: number;
  outcome?: string; device_uptime_ms?: number; cancelled_pointers?: number[] };
type Edge = { id: number; action: number; point: TeachingPoint; at: number; notAfter?:number };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

/** Explicit three-contact protocol. Never falls back to taps, WebSocket or a second owner. */
export class TeachingContacts {
  private sequence = 0;
  private gesture = 0;
  private owner: string | null = null;
  private ready = false;
  private closing = false;
  private ended = false;
  private closedConfirmed = false;
  private queue: Edge[] = [];
  private desired = new Map<number, TeachingPoint>();
  private held = new Set<number>();
  private pending: TeachingInput | null = null;
  private pendingAt = 0;
  private openedAt = performance.now();
  private lastSend = this.openedAt;
  private remove: () => void = () => {};
  private timer: ReturnType<typeof setInterval>;
  private finishClose: ((confirmed: boolean) => void) | null = null;
  private closePromise: Promise<boolean> | null = null;
  private closeAt = 0;
  private receiptRtt: number | null = null;
  private failure: string | null = null;
  private cameraRequest:((applied:boolean)=>void)|null=null;
  private videoPaused=false;
  private cameraTarget:{point:TeachingPoint;deadline:number;at:number;timer:ReturnType<typeof setTimeout>|null}|null=null;
  private stroke: {id:1;origin:TeachingPoint;target:TeachingPoint;deadline:number;phase:'down'|'move'|'up';
    step:number;lastEdgeAt:number;timer:ReturnType<typeof setTimeout>|null;finish:(applied:boolean)=>void}|null=null;
  constructor(private endpoint: DirectControlEndpoint, private binding: DirectVideoBinding,
    private fresh: () => boolean, private journal: (event: TeachingInput) => void,
    private state: (state: 'opening' | 'ready' | 'closing' | 'closed' | 'failed', reason?: string) => void,
    private observedRtt?: (milliseconds: number) => void,
    private idleFresh?:()=>boolean,private neutralStick?:TeachingPoint,private recoverVideoGaps=false) {
    if (!endpoint.sharedInput || endpoint.readyState !== 1) throw Error('shared_input_required');
    this.timer = setInterval(() => this.tick(), 25);
    this.remove = endpoint.listen(value => this.receipt(value));
    if (this.closing || this.ended) return;
    this.state('opening');
    try { this.send({ type: 'touch_open', capture_epoch: binding.captureEpoch,
      frame_width: binding.width, frame_height: binding.height, contact_protocol: 1 }); }
    catch { this.fail('contact_open_failed'); }
  }
  get isReady() { return this.ready && !this.closing && !this.ended; }
  get lastReceiptRttMs() { return this.receiptRtt; }
  get failureReason() { return this.failure; }
  get isVideoPaused(){return this.videoPaused;}
  get isNeutral() { return !this.desired.size && !this.held.size && !this.pending && !this.queue.length; }
  hasContact(id: number) { return this.desired.has(id); }
  private centeredStick(center:TeachingPoint|undefined=this.neutralStick){
    const p=this.desired.get(0);
    return !this.held.has(0)&&!p||!!center&&!!p&&this.held.has(0)&&p.x===center.x&&p.y===center.y;
  }
  canCameraCommand(center:TeachingPoint){
    return this.isReady&&!this.pending&&!this.queue.length&&!this.stroke&&!this.cameraRequest
      &&(this.centeredStick(center)||this.recoverVideoGaps&&this.held.has(0))
      &&![...this.held].some(id=>id!==0&&id!==1)&&!this.desired.has(2);
  }
  /** Exactly one fresh edge. No delayed waveform or old MOVE is queued. */
  cameraCommand(point:TeachingPoint|null,notAfter:number,center:TeachingPoint):Promise<boolean>{
    if(!this.canCameraCommand(center)||point&&(!this.fresh()||!Number.isFinite(notAfter)||performance.now()>=notAfter||notAfter-performance.now()>250))return Promise.resolve(false);
    const before=this.desired.get(1);
    if(!point&&!before||point&&before&&point.x===before.x&&point.y===before.y)return Promise.resolve(true);
    return new Promise(resolve=>{this.cameraRequest=resolve;
      if(this.recoverVideoGaps&&point&&before&&Math.hypot(point.x-before.x,point.y-before.y)>8){
        this.cameraTarget={point:{...point},deadline:notAfter,at:performance.now(),timer:null};this.advanceCamera();
      }else this.set(1,point,notAfter);
      if(!this.isReady){this.cameraRequest?.(false);this.cameraRequest=null;}});
  }
  private advanceCamera(){
    const path=this.cameraTarget;if(!path)return;
    path.timer=setTimeout(()=>{
      path.timer=null;if(this.cameraTarget!==path||!this.isReady)return;
      if(!this.fresh()||performance.now()>=path.deadline){
        if(!this.fresh()&&this.recoverVideoGaps&&this.idleFresh?.())this.videoPaused=true;
        this.neutralize();return;
      }
      const from=this.desired.get(1);if(!from){this.neutralize();return;}
      const dx=path.point.x-from.x,dy=path.point.y-from.y,length=Math.hypot(dx,dy);
      const dt=Math.min(.04,Math.max(.016,(performance.now()-path.at)/1000));path.at=performance.now();
      const scale=Math.min(1,Math.min(this.binding.width,this.binding.height)*.45*dt/length);
      this.set(1,{x:Math.round(from.x+dx*scale),y:Math.round(from.y+dy*scale)},path.deadline);
    },16);
  }
  horizontalStroke(origin:TeachingPoint,targetX:number,notAfter:number):Promise<boolean> {
    if(!this.isReady||!this.isNeutral||this.stroke||this.hasContact(1)||!this.fresh()||performance.now()>=notAfter
      ||!Number.isFinite(notAfter)||notAfter-performance.now()>250||notAfter-performance.now()<170||!Number.isInteger(targetX)||targetX===origin.x
      ||Math.abs(targetX-origin.x)>Math.min(this.binding.width,this.binding.height)*.04+1)return Promise.resolve(false);
    return new Promise(resolve=>{
      this.stroke={id:1,origin:{...origin},target:{x:targetX,y:origin.y},deadline:notAfter,phase:'down',
        step:0,lastEdgeAt:performance.now(),timer:null,finish:resolve};
      this.set(1,origin);
      if(!this.isReady){this.stroke?.finish(false);this.stroke=null;}
    });
  }
  private advanceStroke(){
    const stroke=this.stroke;if(!stroke||stroke.phase==='up')return;
    const advance=()=>{
      stroke.timer=null;
      if(this.stroke!==stroke||!this.isReady)return;
      if(!this.fresh()||performance.now()>=stroke.deadline){this.fail('camera_stroke_expired');return;}
      stroke.lastEdgeAt=performance.now();
      if(stroke.step<4){
        stroke.phase='move';stroke.step++;
        const point={x:Math.round(stroke.origin.x+(stroke.target.x-stroke.origin.x)*stroke.step/4),y:stroke.origin.y};
        if(this.desired.get(1)?.x===point.x){this.advanceStroke();return;}
        this.set(1,point);
      }else{stroke.phase='up';this.set(1,null);}
    };
    // Native ACK means submission, not a rendered game frame. Space movement
    // over several frames instead of collapsing DOWN/MOVE/UP into one tap.
    stroke.timer=setTimeout(advance,Math.max(0,24-(performance.now()-stroke.lastEdgeAt)));
  }
  set(id: number, point: TeachingPoint | null,notAfter?:number) {
    if (!this.isReady) return;
    if (!Number.isInteger(id) || id < 0 || id > 2 || point && (!Number.isInteger(point.x)
      || !Number.isInteger(point.y) || point.x < 0 || point.y < 0 || point.x >= this.binding.width || point.y >= this.binding.height)) {
      this.fail('invalid_contact'); return;
    }
    const before = this.desired.get(id);
    if (!before && !point || before && point && before.x === point.x && before.y === point.y) return;
    if (point) this.desired.set(id, point); else this.desired.delete(id);
    const edge: Edge = { id, action: point ? before ? 2 : 0 : 1, point: point ?? before!, at: performance.now(),notAfter };
    if(notAfter!==undefined&&!Number.isFinite(notAfter)){this.fail('invalid_contact');return;}
    const previous = this.queue.at(-1);
    if (edge.action === 2 && previous?.action === 2 && previous.id === id) this.queue[this.queue.length - 1] = edge;
    else this.queue.push(edge);
    if (this.queue.length > 8) { this.fail('contact_queue_full'); return; }
    this.pump();
  }
  /** Cancel unsent movement and release camera/action even without fresh RGB.
   * A held stick moves to CENTER, preserving one contact instead of double taps.
   * Neither old MOVE nor old camera target can resume when video returns. */
  neutralize(){
    if(!this.isReady)return;
    if(this.cameraTarget?.timer)clearTimeout(this.cameraTarget.timer);this.cameraTarget=null;
    this.cameraRequest?.(false);this.cameraRequest=null;
    const stroke=this.stroke;this.stroke=null;if(stroke?.timer)clearTimeout(stroke.timer);stroke?.finish(false);
    this.queue=this.queue.filter(edge=>this.isNeutralEdge(edge));
    for(const id of [0,1,2]){
      if(!this.held.has(id)){this.desired.delete(id);continue;}
      if(id===0&&this.neutralStick)this.set(0,this.neutralStick);
      else this.set(id,null);
    }
    this.pump();
  }
  private isNeutralEdge(edge:Edge){return edge.action===1||edge.id===0&&edge.action===2&&!!this.neutralStick
    &&edge.point.x===this.neutralStick.x&&edge.point.y===this.neutralStick.y;}
  private send(value: object) {
    const current = this.endpoint.capture();
    if (this.endpoint.readyState !== 1 || this.endpoint.bufferedAmount > 1024
      || !current || current.captureEpoch !== this.binding.captureEpoch
      || current.width !== this.binding.width || current.height !== this.binding.height) throw Error('contact_transport_changed');
    this.endpoint.send(JSON.stringify(value)); this.lastSend = performance.now();
  }
  private pump() {
    if (!this.isReady || this.pending) return;
    const edge = this.queue.shift();
    if (!edge) return;
    if(!this.isNeutralEdge(edge)&&edge.notAfter!==undefined&&performance.now()>=edge.notAfter){
      if(this.recoverVideoGaps)this.neutralize();else this.fail('stale_contact');return;
    }
    if ((!this.fresh()&&!this.isNeutralEdge(edge)) || performance.now() - edge.at >= 200) { this.fail('stale_contact'); return; }
    if (edge.action === 0 && !this.held.size) this.gesture++;
    if (edge.action === 0) this.held.add(edge.id);
    const event: TeachingInput = { stage: 'submitted', at_ms: performance.timeOrigin + performance.now(),
      sequence: ++this.sequence, gesture: this.gesture, action: edge.action, pointer_id: edge.id, ...edge.point };
    this.pending = event; this.pendingAt = performance.now();
    try { this.journal(event); this.send({ type: 'touch_contact_event', sequence: event.sequence,
      gesture: event.gesture, action: event.action, pointer_id: event.pointer_id, ...edge.point }); }
    catch { this.fail('contact_send_unknown'); }
  }
  private receipt(value: unknown) {
    if (this.ended || !object(value)) return;
    if (value.type === 'input_availability' && value.state !== 'manual') { this.fail('input_reserved'); return; }
    if (value.type !== 'touch_session' && value.type !== 'shared_input_status') return;
    if (value.session_id !== this.endpoint.session || value.capture_epoch !== this.binding.captureEpoch
      || value.contact_protocol !== 1 || value.max_pointers !== 3 || typeof value.owner !== 'string'
      || !/^[0-9a-f]{32}$/.test(value.owner) || this.owner && value.owner !== this.owner) { this.fail('contact_protocol_required'); return; }
    if (value.type === 'touch_session') {
      if (this.owner || value.frame_width !== this.binding.width || value.frame_height !== this.binding.height) {
        this.fail('contact_binding_invalid'); return;
      }
      this.owner = value.owner; return;
    }
    if (!this.owner || !Number.isSafeInteger(value.device_uptime_ms) || (value.device_uptime_ms as number) < 0) {
      this.fail('contact_receipt_invalid'); return;
    }
    if (value.outcome === 'closed' && value.sequence === 0 && value.gesture === 0 && value.action === 3 && value.pointer_id === -1) { this.finish(true,value.device_uptime_ms as number); return; }
    if (this.closing && !this.pending) return;
    if (value.outcome === 'ready' && value.sequence === 0 && value.gesture === 0 && value.action === 4 && value.pointer_id === -1 && !this.ready) {
      this.ready = true; this.state('ready'); return;
    }
    const pending = this.pending;
    // A busy browser may deliver a late message before its overdue timer tick.
    // Such an ACK cannot authorize another queued command or seal a recording.
    if (pending && performance.now()-this.pendingAt >= 500) { this.fail('contact_ack_timeout'); return; }
    if (!pending || value.sequence !== pending.sequence || value.gesture !== pending.gesture
      || value.action !== pending.action || value.pointer_id !== pending.pointer_id
      || value.outcome !== (pending.action === 4 ? 'alive' : 'applied')) { this.fail('contact_receipt_unknown'); return; }
    this.receiptRtt = Math.max(0,performance.now()-this.pendingAt);
    try { this.observedRtt?.(this.receiptRtt); } catch { /* Scalar telemetry cannot interrupt control. */ }
    try { this.journal({ ...pending, stage: 'receipt', at_ms: performance.timeOrigin + performance.now(),
      outcome: value.outcome as string, device_uptime_ms: value.device_uptime_ms as number }); }
    catch { this.fail('contact_journal_failed'); return; }
    if (pending.action === 1) this.held.delete(pending.pointer_id);
    this.pending = null;
    if(pending.pointer_id===1&&this.cameraRequest){
      const path=this.cameraTarget;
      if(path&&(pending.x!==path.point.x||pending.y!==path.point.y))this.advanceCamera();
      else{this.cameraTarget=null;const done=this.cameraRequest;this.cameraRequest=null;done(true);}
    }
    const stroke=this.stroke;
    if(stroke&&pending.pointer_id===stroke.id){
      if(stroke.phase==='up'){
        this.stroke=null;stroke.finish(true);
      }else if(!this.fresh()||performance.now()>=stroke.deadline){
        this.fail('camera_stroke_expired');return;
      }else this.advanceStroke();
    }
    this.pump();
  }
  private tick() {
    const now = performance.now();
    if (this.closing) { if (now - this.closeAt >= 2500) this.finish(false); return; }
    if (this.ended) return;
    const empty=!this.queue.length&&(!this.pending||this.pending.action===4)
      &&(!this.desired.size&&!this.held.size||!!this.neutralStick&&this.centeredStick()
        &&![...this.held].some(id=>id!==0)&&![...this.desired.keys()].some(id=>id!==0));
    if(!this.fresh()){
      if(this.recoverVideoGaps&&this.idleFresh?.()){
        if(!this.videoPaused){this.videoPaused=true;this.neutralize();}
      }else if(!(empty&&this.idleFresh?.())){this.fail('contact_video_stale');return;}
    }else this.videoPaused=false;
    if (this.endpoint.readyState !== 1) { this.fail('contact_channel_closed'); return; }
    if (this.pending && now - this.pendingAt >= 500) { this.fail('contact_ack_timeout'); return; }
    if (!this.ready && now - this.openedAt >= 6000) { this.fail('contact_ready_timeout'); return; }
    if (!this.isReady || this.pending || now - this.lastSend < 300) return;
    if(this.stroke)return;
    const event: TeachingInput = { stage: 'submitted', at_ms: performance.timeOrigin + now,
      sequence: ++this.sequence, gesture: this.held.size ? this.gesture : 0, action: 4, pointer_id: -1 };
    this.pending = event; this.pendingAt = now;
    try { this.journal(event); this.send({ type: 'touch_event', sequence: event.sequence,
      gesture: event.gesture, action: 4, x: 0, y: 0 }); } catch { this.fail('heartbeat_unknown'); }
  }
  private fail(reason: string) { if (!this.ended && !this.closing) { this.failure=reason; this.state('failed', reason); void this.close(); } }
  close(): Promise<boolean> {
    if (this.closePromise) return this.closePromise;
    if (this.ended) return Promise.resolve(this.closedConfirmed);
    this.closing = true; this.ready = false; this.queue = []; this.desired.clear(); this.closeAt = performance.now();
    if(this.cameraTarget?.timer)clearTimeout(this.cameraTarget.timer);this.cameraTarget=null;
    this.cameraRequest?.(false);this.cameraRequest=null;
    const stroke=this.stroke;this.stroke=null;if(stroke?.timer)clearTimeout(stroke.timer);stroke?.finish(false);
    this.closePromise = new Promise(resolve => { this.finishClose = resolve; });
    this.state('closing');
    try { this.send({ type: 'touch_close' }); } catch { this.finish(false); }
    return this.closePromise;
  }
  private finish(confirmed: boolean, deviceUptime?: number) {
    if (this.ended) return;
    this.ended = true; this.ready = false; clearInterval(this.timer); this.remove();
    if(this.cameraTarget?.timer)clearTimeout(this.cameraTarget.timer);this.cameraTarget=null;
    this.cameraRequest?.(false);this.cameraRequest=null;
    const stroke=this.stroke;this.stroke=null;if(stroke?.timer)clearTimeout(stroke.timer);stroke?.finish(false);
    try { this.journal({ stage: 'closed', at_ms: performance.timeOrigin + performance.now(), sequence: 0,
      gesture: 0, action: 3, pointer_id: -1, outcome: confirmed ? 'closed' : 'unknown',
      ...(confirmed?{device_uptime_ms:deviceUptime,cancelled_pointers:[...this.held].sort()}: {}) }); } catch { confirmed = false; }
    this.closedConfirmed=confirmed;
    this.state(confirmed ? 'closed' : 'failed', confirmed ? undefined : 'release_unknown');
    this.finishClose?.(confirmed);
  }
}

export function stickPoint(keys: ReadonlySet<string>, center: TeachingPoint, radius: number, slow = false): TeachingPoint | null {
  const x = Number(keys.has('KeyD')) - Number(keys.has('KeyA'));
  const y = Number(keys.has('KeyS')) - Number(keys.has('KeyW'));
  if (!x && !y) return null;
  const scale = radius * (slow ? 0.4 : 1) / Math.hypot(x, y);
  return { x: Math.round(center.x + x * scale), y: Math.round(center.y + y * scale) };
}
