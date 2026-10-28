import {webcrypto} from 'node:crypto';
import {TextEncoder} from 'node:util';
import {saveRouteDebugReport} from '@/src/features/stream/routeDebugStorage';

type Fixture={handle:FileSystemDirectoryHandle;children:Map<string,Fixture>;files:Map<string,Uint8Array>;writes:string[]};
function directory(failReport=false):Fixture {
  const files=new Map<string,Uint8Array>(),children=new Map<string,Fixture>(),writes:string[]=[];
  const handle={getDirectoryHandle:async(name:string,options?:{create?:boolean})=>{if(!children.has(name)){
    if(!options?.create)throw Object.assign(Error('missing'),{name:'NotFoundError'});children.set(name,directory(failReport));}return children.get(name)!.handle;},
    getFileHandle:async(name:string,options?:{create?:boolean})=>{
      if(!files.has(name)){if(!options?.create)throw Object.assign(Error('missing'),{name:'NotFoundError'});files.set(name,new Uint8Array());}
      return {getFile:async()=>({size:files.get(name)!.length,text:async()=>Buffer.from(files.get(name)!).toString('utf8'),arrayBuffer:async()=>Uint8Array.from(files.get(name)!).buffer}),
        createWritable:async()=>({write:async(data:ArrayBuffer)=>{writes.push(name);files.set(name,new Uint8Array(data));},
          close:async()=>{if(failReport&&name==='report.json')throw Error('close_unknown');},abort:async()=>{}})};
    }} as unknown as FileSystemDirectoryHandle;
  return {handle,children,files,writes};
}
beforeEach(()=>{Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});});

test('reports are scope-bound, sealed, verified on repeat and never overwrite a changed report',async()=>{
  const root=directory();Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>root.handle,estimate:async()=>({quota:2**30,usage:0})}});
  const scope='a'.repeat(32),clip='b'.repeat(32),run='c'.repeat(32),report={state:'unknown',inliers:0};
  await expect(saveRouteDebugReport(scope,clip,run,report)).resolves.toMatchObject({state:'saved'});
  const folder=root.children.get('sphere-route-debug-'+scope)!.children.get(clip)!.children.get(run)!;
  expect(folder.writes).toEqual(['intent.json','report.json','COMPLETE']);
  await expect(saveRouteDebugReport(scope,clip,run,report)).resolves.toMatchObject({state:'existing'});
  expect(folder.writes).toHaveLength(3);
  folder.files.set('report.json',new TextEncoder().encode('corrupted'));
  await expect(saveRouteDebugReport(scope,clip,run,report)).resolves.toMatchObject({state:'unconfirmed'});
  expect(folder.writes).toHaveLength(3);
});
test('uncertain write and invalid scope never become a successful repeated save',async()=>{
  const root=directory(true);Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>root.handle,estimate:async()=>({quota:2**30,usage:0})}});
  const scope='d'.repeat(32),clip='e'.repeat(32),run='f'.repeat(32);
  await expect(saveRouteDebugReport('../other',clip,run,{})).rejects.toThrow('identity');
  await expect(saveRouteDebugReport(scope,clip,run,{})).rejects.toThrow('close_unknown');
  await expect(saveRouteDebugReport(scope,clip,run,{})).resolves.toMatchObject({state:'unconfirmed'});
  const folder=root.children.get('sphere-route-debug-'+scope)!.children.get(clip)!.children.get(run)!;
  expect(folder.files.has('COMPLETE')).toBe(false);expect(folder.writes).toHaveLength(2);
});
