'use client';
import {useEffect,useRef,useState} from 'react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
type Geometry={cameras:{center:number[];ticks_90k:number}[];points:number[][];camera_path_units:number;metric_scale:null};

export default function ReconstructedScene({job,status}:{job:ReconstructionJob;status:ReconstructionState}) {
  const host=useRef<HTMLDivElement>(null),reset=useRef<()=>void>(()=>{});
  const [error,setError]=useState<string|null>(null),[details,setDetails]=useState('Загружаем восстановленные камеры…');
  useEffect(()=>{
    let retired=false,dispose=()=>{};const abort=new AbortController();setError(null);
    void(async()=>{
      const [THREE,{OrbitControls}]=await Promise.all([import('three'),import('three/addons/controls/OrbitControls.js')]);
      const geometry=await(await reconstructionRequest(`/jobs/${job.id}/geometry`,job,{signal:abort.signal})).json() as Geometry;
      if(!Array.isArray(geometry.cameras)||geometry.cameras.length>240||!Array.isArray(geometry.points)||geometry.points.length>60000
        ||geometry.cameras.some(c=>c.center.length!==3||c.center.some(n=>!Number.isFinite(n)))
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
        scene.add(new THREE.Points(buffer,material));objects.push(buffer,material);
      }
      const centers=geometry.cameras.map(c=>new THREE.Vector3(...c.center as [number,number,number]));
      const lineGeometry=new THREE.BufferGeometry().setFromPoints(centers),lineMaterial=new THREE.LineBasicMaterial({color:'#47e6b1',depthTest:false});
      const line=new THREE.Line(lineGeometry,lineMaterial);line.renderOrder=10;scene.add(line);objects.push(lineGeometry,lineMaterial);
      const bounds=new THREE.Box3().setFromPoints([...centers,...points.filter((_,i)=>i%20===0).map(p=>new THREE.Vector3(...p.slice(0,3) as [number,number,number]))]);
      const center=bounds.getCenter(new THREE.Vector3()),radius=Math.max(bounds.getSize(new THREE.Vector3()).length()*.45,.1);
      const frame=()=>{controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(radius,-radius*.6,-radius));controls.update();};reset.current=frame;frame();
      const resize=()=>{const width=element.clientWidth,height=element.clientHeight;renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();};
      const observer=new ResizeObserver(resize);observer.observe(element);resize();
      renderer.setAnimationLoop(()=>{controls.update();renderer.render(scene,camera);});
      dispose=()=>{observer.disconnect();renderer.setAnimationLoop(null);controls.dispose();for(const object of objects)object.dispose();renderer.dispose();renderer.domElement.remove();};
      setDetails(`${geometry.cameras.length} камер · ${points.length.toLocaleString('ru')} опорных точек · путь камеры ${geometry.camera_path_units.toFixed(2)} усл. ед.`);
      if(status.dense_available){
        const {SparkRenderer,SplatMesh}=await import('@sparkjsdev/spark');
        if(retired)return;
        const spark=new SparkRenderer({renderer});scene.add(spark);objects.push(spark);
        const splat=new SplatMesh({url:`http://127.0.0.1:3342/jobs/${job.id}/scene`,requestHeader:{'X-Sphere-Reconstruction':'1','X-Job-Key':job.key},maxSplats:750000,lod:false});
        objects.push(splat);await splat.initialized;
        if(retired)return;scene.add(splat);
        setDetails(`${geometry.cameras.length} камер · плотная Gaussian-сцена · путь камеры ${geometry.camera_path_units.toFixed(2)} усл. ед.`);
      }
    })().catch(e=>{if(!retired)setError(e instanceof Error?e.message:'Не удалось открыть сцену.');});
    return()=>{retired=true;abort.abort();dispose();};
  },[job,status.dense_available]);
  return <div className="overflow-hidden rounded-xl border border-border bg-background">
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"><p className="text-xs text-muted-foreground">{details}</p><Button size="sm" variant="outline" onClick={()=>reset.current()}>Вписать сцену</Button></div>
    <div ref={host} className="h-[480px] w-full" aria-label="Восстановленная 3D-сцена" />
    {error&&<p role="alert" className="px-4 py-2 text-sm text-destructive">{error}</p>}
    <p className="px-4 py-3 text-xs text-muted-foreground">Левая кнопка — вращать · правая — перемещать · колесо — приближать. Зелёная линия — восстановленный путь камеры. Масштаб в метрах и проходимость не подтверждены.</p>
  </div>;
}
