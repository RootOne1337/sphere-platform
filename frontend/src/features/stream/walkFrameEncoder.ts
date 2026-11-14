type Encoded={blob:Blob;sha:string};
export type EncoderDiagnostic={captureMode:'video_frame'|'bitmap'|'canvas';captureMs:number;workerMs:number;encodeMs:number;hashMs:number};
type Pending={resolve:(v:Encoded)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>;sentAt:number;captureMs:number;mode:EncoderDiagnostic['captureMode']};
/** One transferable bitmap and one query; encoding/hash never queue up. */
export class WalkFrameEncoder{
  private worker:Worker|null=null;private pending:Pending|null=null;private closed=false;private capturing=false;
  private diagnostic:EncoderDiagnostic|null=null;
  snapshot(){return this.diagnostic?{...this.diagnostic}:null;}
  constructor(){
    if(typeof Worker==='undefined'||typeof OffscreenCanvas==='undefined'||typeof VideoFrame==='undefined'&&typeof createImageBitmap!=='function')return;
    try{
      const worker=this.worker=new Worker('/walk-frame-encoder.js');
      worker.onmessage=event=>{
        const p=this.pending;if(!p)return;this.pending=null;clearTimeout(p.timer);
        const value=event.data;
        if(value?.type!=='encoded'||!(value.blob instanceof Blob)||value.blob.type!=='image/jpeg'||value.blob.size>384*1024||!/^[a-f0-9]{64}$/.test(value.sha)){
          this.disable();p.reject(Error('walk_encoder_retry'));return;
        }
        const duration=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<10000?v:0;
        this.diagnostic={captureMode:p.mode,captureMs:p.captureMs,workerMs:performance.now()-p.sentAt,
          encodeMs:duration(value.encodeMs),hashMs:duration(value.hashMs)};
        p.resolve({blob:value.blob,sha:value.sha});
      };
      worker.onerror=()=>{this.disable();};
    }catch{this.disable();}
  }
  private disable(){
    this.worker?.terminate();this.worker=null;
    const p=this.pending;this.pending=null;if(p){clearTimeout(p.timer);p.reject(Error('walk_encoder_retry'));}
  }
  close(){this.closed=true;this.disable();}
  async encode(video:HTMLVideoElement,fallback:HTMLCanvasElement):Promise<Encoded>{
    if(this.closed||this.capturing)throw Error('walk_encoder_unavailable');
    this.capturing=true;
    try{
      if(this.worker){
        const began=performance.now(),mode=typeof VideoFrame==='function'?'video_frame':'bitmap';
        // Snapshot the displayed frame immediately. Resizing/readback belongs
        // in the worker; an asynchronous createImageBitmap(video, resize) can
        // stall the capture path and return after this pose's permit expired.
        const bitmap=mode==='video_frame'?new VideoFrame(video,{timestamp:Math.round(began*1000)}):
          await createImageBitmap(video,{resizeWidth:960,resizeHeight:540,resizeQuality:'low'});
        if(this.closed||!this.worker){bitmap.close();throw Error('walk_encoder_retry');}
        return await new Promise<Encoded>((resolve,reject)=>{
          this.pending={resolve,reject,timer:setTimeout(()=>this.disable(),750),sentAt:performance.now(),captureMs:performance.now()-began,mode};
          try{this.worker!.postMessage({type:'encode',bitmap},[bitmap]);}catch{bitmap.close();this.disable();}
        });
      }
      const began=performance.now();
      const context=fallback.getContext('2d');if(!context)throw Error('walk_canvas_unavailable');
      context.drawImage(video,0,0,960,540);
      const blob=await new Promise<Blob>((resolve,reject)=>fallback.toBlob(v=>v?resolve(v):reject(Error('walk_jpeg_unavailable')),'image/jpeg',.92));
      if(this.closed)throw Error('walk_encoder_unavailable');
      const encodedAt=performance.now();
      const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer())),n=>n.toString(16).padStart(2,'0')).join('');
      if(this.closed)throw Error('walk_encoder_unavailable');
      this.diagnostic={captureMode:'canvas',captureMs:0,workerMs:0,encodeMs:encodedAt-began,hashMs:performance.now()-encodedAt};
      return {blob,sha};
    }catch(error){if(this.worker){this.disable();throw Error('walk_encoder_retry');}throw error;}
    finally{this.capturing=false;}
  }
}
