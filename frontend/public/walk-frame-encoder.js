'use strict';
// Fixed analysis size; independent of the original full-resolution recording.
const canvas=new OffscreenCanvas(960,540),context=canvas.getContext('2d',{alpha:false});
let busy=false;
self.onmessage=async event=>{
  const bitmap=event.data?.bitmap;
  if(busy||event.data?.type!=='encode'||!bitmap){bitmap?.close();self.postMessage({type:'failed'});return;}
  busy=true;
  try{
    context.drawImage(bitmap,0,0,960,540);
    const blob=await canvas.convertToBlob({type:'image/jpeg',quality:.92});
    if(blob.size>384*1024)throw Error('quota');
    const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer())),n=>n.toString(16).padStart(2,'0')).join('');
    self.postMessage({type:'encoded',blob,sha});
  }catch{self.postMessage({type:'failed'});}
  finally{bitmap.close();busy=false;}
};
