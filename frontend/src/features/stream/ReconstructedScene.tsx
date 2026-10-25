'use client';
import {useEffect,useRef,useState} from 'react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
type Geometry={cameras:{center:number[];ticks_90k:number;camera_to_world?:number[][];intrinsics?:{width:number;height:number;fx:number;fy:number;cx:number;cy:number}}[];points:number[][];camera_path_units:number;metric_scale:null};

export default function ReconstructedScene({job,status}:{job:ReconstructionJob;status:ReconstructionState}) {
  const host=useRef<HTMLDivElement>(null),reset=useRef<()=>void>(()=>{}),recordedView=useRef<(index:number)=>void>(()=>{});
  const pointObject=useRef<{visible:boolean}|null>(null),lineObject=useRef<{visible:boolean}|null>(null);
  const [showPoints,setShowPoints]=useState(false),[showPath,setShowPath]=useState(false);
  const [recordedIndex,setRecordedIndex]=useState(0),[cameraCount,setCameraCount]=useState(0),[recordedSeconds,setRecordedSeconds]=useState(0);
  const options=useRef({points:false,path:false});options.current={points:showPoints,path:showPath};
  const [error,setError]=useState<string|null>(null),[details,setDetails]=useState('Загружаем восстановленные камеры…');
  useEffect(()=>{
    let retired=false,dispose=()=>{};const abort=new AbortController();setError(null);
    void(async()=>{
      const [THREE,{OrbitControls}]=await Promise.all([import('three'),import('three/addons/controls/OrbitControls.js')]);
      const geometry=await(await reconstructionRequest(`/jobs/${job.id}/geometry`,job,{signal:abort.signal})).json() as Geometry;
      if(!Array.isArray(geometry.cameras)||geometry.cameras.length>240||!Array.isArray(geometry.points)||geometry.points.length>60000
        ||geometry.cameras.some(c=>c.center.length!==3||c.center.some(n=>!Number.isFinite(n))||c.camera_to_world&&(c.camera_to_world.length!==3||c.camera_to_world.some(row=>row.length!==4||row.some(n=>!Number.isFinite(n))))
          ||c.intrinsics&&(!Object.values(c.intrinsics).every(Number.isFinite)||c.intrinsics.width<=0||c.intrinsics.height<=0||c.intrinsics.fx<=0||c.intrinsics.fy<=0))
        ||geometry.points.some(p=>p.length!==6||p.some(n=>!Number.isFinite(n))))throw Error('Повреждена геометрия результата.');
      if(retired||!host.current)return;
      const element=host.current,scene=new THREE.Scene();scene.background=new THREE.Color('#080c17');
      const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));element.appendChild(renderer.domElement);
      const camera=new THREE.PerspectiveCamera(55,1,.001,10000);camera.up.set(0,-1,0);
      const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.screenSpacePanning=true;
      const objects: {dispose:()=>void}[]=[];const points=geometry.points;
      if(points.length){
        const buffer=new THREE.BufferGeometry();buffer.setAttribute('position',new THREE.Float32BufferAttribute(points.flatMap(p=>p.slice(0,3)),3));
        buffer.setAttribute('color',new THREE.Float32BufferAttribute(points.flatMap(p=>p.slice(3,6).map(c=>c/255)),3));
        const material=new THREE.PointsMaterial({size:2,sizeAttenuation:false,vertexColors:true});
        const cloud=new THREE.Points(buffer,material);cloud.visible=options.current.points;pointObject.current=cloud;
        scene.add(cloud);objects.push(buffer,material);
      }
      const centers=geometry.cameras.map(c=>new THREE.Vector3(...c.center as [number,number,number]));
      const lineGeometry=new THREE.BufferGeometry().setFromPoints(centers),lineMaterial=new THREE.LineBasicMaterial({color:'#47e6b1',depthTest:false});
      const line=new THREE.Line(lineGeometry,lineMaterial);line.visible=options.current.path;lineObject.current=line;line.renderOrder=10;scene.add(line);objects.push(lineGeometry,lineMaterial);
      const bounds=new THREE.Box3().setFromPoints([...centers,...points.filter((_,i)=>i%20===0).map(p=>new THREE.Vector3(...p.slice(0,3) as [number,number,number]))]);
      const center=bounds.getCenter(new THREE.Vector3()),radius=Math.max(bounds.getSize(new THREE.Vector3()).length()*.45,.1);
      let referenceProjection=false,projectionCamera=geometry.cameras[0];
      const project=()=>{const k=projectionCamera?.intrinsics;if(referenceProjection&&k){const n=camera.near;camera.projectionMatrix.makePerspective(-k.cx*n/k.fx,(k.width-k.cx)*n/k.fx,k.cy*n/k.fy,-(k.height-k.cy)*n/k.fy,n,camera.far);camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();}else camera.updateProjectionMatrix();};
      const frame=()=>{referenceProjection=false;project();camera.up.set(0,-1,0);controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(radius,-radius*.6,-radius));controls.update();};reset.current=frame;
      const fromRecording=(index:number)=>{
        const first=geometry.cameras[Math.max(0,Math.min(index,geometry.cameras.length-1))],pose=first?.camera_to_world;if(!pose){frame();return;}
        projectionCamera=first;setRecordedSeconds(first.ticks_90k/90000);
        const distance=Math.max(new THREE.Box3().setFromPoints(centers).getSize(new THREE.Vector3()).length()*.15,.05);
        referenceProjection=true;project();camera.position.set(...first.center as [number,number,number]);camera.up.set(-pose[0][1],-pose[1][1],-pose[2][1]);
        controls.target.copy(camera.position).add(new THREE.Vector3(pose[0][2],pose[1][2],pose[2][2]).multiplyScalar(distance));controls.update();
      };recordedView.current=fromRecording;setCameraCount(geometry.cameras.length);setRecordedIndex(0);fromRecording(0);
      const resize=()=>{const k=geometry.cameras[0]?.intrinsics,aspect=k?k.width/k.height:16/9;const width=Math.min(element.clientWidth,element.clientHeight*aspect),height=width/aspect;renderer.setSize(width,height);camera.aspect=aspect;project();};
      const observer=new ResizeObserver(resize);observer.observe(element);resize();
      renderer.setAnimationLoop(()=>{controls.update();renderer.render(scene,camera);});
      dispose=()=>{pointObject.current=null;lineObject.current=null;observer.disconnect();renderer.setAnimationLoop(null);controls.dispose();for(const object of objects)object.dispose();renderer.dispose();renderer.domElement.remove();};
      setDetails(`${geometry.cameras.length} камер · ${points.length.toLocaleString('ru')} опорных точек · путь камеры ${geometry.camera_path_units.toFixed(2)} усл. ед.`);
      if(status.dense_available||status.dense_partial_available){
        const {SparkRenderer,SplatMesh}=await import('@sparkjsdev/spark');
        if(retired)return;
        const spark=new SparkRenderer({renderer});scene.add(spark);objects.push(spark);
        const splat=new SplatMesh({url:`http://127.0.0.1:3342/jobs/${job.id}/scene`,requestHeader:{'X-Sphere-Reconstruction':'1','X-Job-Key':job.key},maxSplats:750000,lod:false});
        objects.push(splat);await splat.initialized;
        if(retired)return;scene.add(splat);
        setDetails(`${geometry.cameras.length} камер · ${status.dense_partial_available?'промежуточная':'плотная'} Gaussian-сцена · путь камеры ${geometry.camera_path_units.toFixed(2)} усл. ед.`);
      }
    })().catch(e=>{if(!retired)setError(e instanceof Error?e.message:'Не удалось открыть сцену.');});
    return()=>{retired=true;abort.abort();dispose();};
  },[job,status.dense_available,status.dense_partial_available]);
  return <div className="overflow-hidden rounded-xl border border-border bg-background">
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"><p className="text-xs text-muted-foreground">{details}</p><div className="flex gap-2"><Button size="sm" variant="outline" onClick={()=>recordedView.current(recordedIndex)}>Камера прохода</Button><Button size="sm" variant="outline" onClick={()=>reset.current()}>Вписать сцену</Button></div></div>
    {cameraCount>0&&<label className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3 text-xs text-muted-foreground"><span>Ракурс прохода {recordedIndex+1}/{cameraCount} · {recordedSeconds.toFixed(1)} с</span><input className="min-w-40 flex-1 accent-emerald-500" aria-label="Ракурс записанного прохода" type="range" min={0} max={cameraCount-1} step={1} value={recordedIndex} onChange={e=>{const index=Number(e.target.value);setRecordedIndex(index);recordedView.current(index);}}/></label>}
    <div className="flex flex-wrap gap-4 border-t border-border px-4 py-2 text-xs text-muted-foreground"><label className="flex items-center gap-2"><input type="checkbox" checked={showPoints} onChange={e=>{setShowPoints(e.target.checked);if(pointObject.current)pointObject.current.visible=e.target.checked;}}/>Опорные точки поверх сцены</label><label className="flex items-center gap-2"><input type="checkbox" checked={showPath} onChange={e=>{setShowPath(e.target.checked);if(lineObject.current)lineObject.current.visible=e.target.checked;}}/>Траектория камеры</label></div>
    <div ref={host} className="flex h-[480px] w-full items-center justify-center bg-black" aria-label="Восстановленная 3D-сцена" />
    {error&&<p role="alert" className="px-4 py-2 text-sm text-destructive">{error}</p>}
    <p className="px-4 py-3 text-xs text-muted-foreground">Левая кнопка — вращать · правая — перемещать · колесо — приближать. Зелёная линия — восстановленный путь камеры. Масштаб в метрах и проходимость не подтверждены.</p>
  </div>;
}
