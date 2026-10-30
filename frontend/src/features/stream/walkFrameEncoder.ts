type Encoded={blob:Blob;sha:string};
type Pending={resolve:(v:Encoded)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>};
/** One transferable bitmap and one query; encoding/hash never queue up. */
export class WalkFrameEncoder{
  private worker:Worker|null=null;private pending:Pending|null=null;private closed=false;private capturing=false;
  constructor(){
    if(typeof Worker==='undefined'||typeof OffscreenCanvas==='undefined'||typeof createImageBitmap!=='function')return;
    try{
      const worker=this.worker=new Worker('/walk-frame-encoder.js');
      worker.onmessage=event=>{
        const p=this.pending;if(!p)return;this.pending=null;clearTimeout(p.timer);
        const value=event.data;
        if(value?.type!=='encoded'||!(value.blob instanceof Blob)||value.blob.type!=='image/jpeg'||value.blob.size>384*1024||!/^[a-f0-9]{64}$/.test(value.sha)){
          this.disable();p.reject(Error('walk_encoder_retry'));return;
        }
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
        const bitmap=await createImageBitmap(video,{resizeWidth:960,resizeHeight:540,resizeQuality:'low'});
        if(this.closed||!this.worker){bitmap.close();throw Error('walk_encoder_retry');}
        return await new Promise<Encoded>((resolve,reject)=>{
          this.pending={resolve,reject,timer:setTimeout(()=>this.disable(),750)};
          try{this.worker!.postMessage({type:'encode',bitmap},[bitmap]);}catch{bitmap.close();this.disable();}
        });
      }
      const context=fallback.getContext('2d');if(!context)throw Error('walk_canvas_unavailable');
      context.drawImage(video,0,0,960,540);
      const blob=await new Promise<Blob>((resolve,reject)=>fallback.toBlob(v=>v?resolve(v):reject(Error('walk_jpeg_unavailable')),'image/jpeg',.92));
      const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer())),n=>n.toString(16).padStart(2,'0')).join('');
      return {blob,sha};
    }catch(error){if(this.worker){this.disable();throw Error('walk_encoder_retry');}throw error;}
    finally{this.capturing=false;}
  }
}
