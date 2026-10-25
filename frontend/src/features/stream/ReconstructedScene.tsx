'use client';
import {useEffect,useRef,useState} from 'react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
import type {BufferGeometry,Material,Mesh,Texture} from 'three';
import {loadSurface} from './surfaceAsset';
import {routeCoverage,type RecordedCamera} from './routeCoverage';
import RecordedSourceFrame from './RecordedSourceFrame';

type SurfaceStyle='texture'|'solid'|'normal'|'wire';
type Geometry={cameras:{center:number[];ticks_90k:number;camera_to_world?:number[][];intrinsics?:{width:number;height:number;fx:number;fy:number;cx:number;cy:number}}[];points:number[][];camera_path_units:number;metric_scale:null};

export default function ReconstructedScene({job,status}:{job:ReconstructionJob;status:ReconstructionState}) {
  const host=useRef<HTMLDivElement>(null),reset=useRef<()=>void>(()=>{}),recordedView=useRef<(index:number)=>void>(()=>{});
  const wholeRoute=useRef<()=>void>(()=>{});
  const [coverage,setCoverage]=useState<ReturnType<typeof routeCoverage>>(null),[recordedImage,setRecordedImage]=useState(''),[compareSource,setCompareSource]=useState(false);
  const panel=useRef<HTMLDivElement>(null),[expanded,setExpanded]=useState(false);
  useEffect(()=>{const update=()=>setExpanded(document.fullscreenElement===panel.current);document.addEventListener('fullscreenchange',update);return()=>document.removeEventListener('fullscreenchange',update);},[]);
  const pointObject=useRef<{visible:boolean}|null>(null),lineObject=useRef<{visible:boolean}|null>(null);
  const [showPoints,setShowPoints]=useState(false),[showPath,setShowPath]=useState(false);
  const [recordedIndex,setRecordedIndex]=useState(0),[cameraCount,setCameraCount]=useState(0),[recordedSeconds,setRecordedSeconds]=useState(0);
  const [representation,setRepresentation]=useState<'surface'|'gaussian'>(status.surface?.available?'surface':'gaussian');
  const [surfaceStyle,setSurfaceStyle]=useState<SurfaceStyle>('texture'),[downloading,setDownloading]=useState(false);
  const styleRef=useRef<(value:SurfaceStyle)=>void>(()=>{}),style=useRef(surfaceStyle);style.current=surfaceStyle;
  const surfaceReady=status.surface?.available===true,surfaceHash=status.surface?.result?.sha256;
  const surfaceIdentity=status.surface?.id;
  const latestStatus=useRef(status);latestStatus.current=status;
  useEffect(()=>{if(surfaceReady)setRepresentation('surface');},[surfaceReady]);
  const options=useRef({points:false,path:false});options.current={points:showPoints,path:showPath};
  const [error,setError]=useState<string|null>(null),[details,setDetails]=useState('Загружаем восстановленные камеры…');
  useEffect(()=>{
    let retired=false,dispose=()=>{};const abort=new AbortController();setError(null);
    void(async()=>{
      const [THREE,{OrbitControls}]=await Promise.all([import('three'),import('three/addons/controls/OrbitControls.js')]);
      const geometry=await(await reconstructionRequest(`/jobs/${job.id}/geometry`,job,{signal:abort.signal})).json() as Geometry;
      if(!Array.isArray(geometry.cameras)||!geometry.cameras.length||geometry.cameras.length>240||!Array.isArray(geometry.points)||geometry.points.length>60000
        ||geometry.cameras.some(c=>c.center.length!==3||c.center.some(n=>!Number.isFinite(n))||c.camera_to_world&&(c.camera_to_world.length!==3||c.camera_to_world.some(row=>row.length!==4||row.some(n=>!Number.isFinite(n))))
          ||c.intrinsics&&(!Object.values(c.intrinsics).every(Number.isFinite)||c.intrinsics.width<=0||c.intrinsics.height<=0||c.intrinsics.fx<=0||c.intrinsics.fy<=0))
        ||geometry.points.some(p=>p.length!==6||p.some(n=>!Number.isFinite(n))))throw Error('Повреждена геометрия результата.');
      const allCameras=geometry.cameras as (typeof geometry.cameras[number]&RecordedCamera)[];
      setCoverage(routeCoverage(allCameras,representation==='surface'&&latestStatus.current.surface?.result?latestStatus.current.surface.result.source_images:allCameras.map(c=>c.image)));
      if(representation==='surface'&&latestStatus.current.surface?.result){
        const included=new Set(latestStatus.current.surface.result.source_images);geometry.cameras=geometry.cameras.filter(c=>included.has((c as typeof c&{image:string}).image));
        if(!geometry.cameras.length)throw Error('Камеры модели не совпадают с проходом.');
      }
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
      const line=new THREE.Line(lineGeometry,lineMaterial);line.renderOrder=10;
      const contextGeometry=new THREE.BufferGeometry().setFromPoints(allCameras.map(c=>new THREE.Vector3(...c.center as [number,number,number]))),contextMaterial=new THREE.LineBasicMaterial({color:'#72859d',depthTest:false,transparent:true,opacity:.55});
      const pathGroup=new THREE.Group();pathGroup.add(new THREE.Line(contextGeometry,contextMaterial),line);pathGroup.visible=options.current.path;lineObject.current=pathGroup;scene.add(pathGroup);objects.push(lineGeometry,lineMaterial,contextGeometry,contextMaterial);
      const bounds=new THREE.Box3().setFromPoints([...centers,...points.filter((_,i)=>i%20===0).map(p=>new THREE.Vector3(...p.slice(0,3) as [number,number,number]))]);
      const center=bounds.getCenter(new THREE.Vector3());let radius=Math.max(bounds.getSize(new THREE.Vector3()).length()*.45,.1);
      const fullBounds=new THREE.Box3().setFromPoints(allCameras.map(c=>new THREE.Vector3(...c.center as [number,number,number]))),fullCenter=fullBounds.getCenter(new THREE.Vector3()),fullRadius=Math.max(fullBounds.getSize(new THREE.Vector3()).length()*.6,.1);
      let referenceProjection=false,projectionCamera=geometry.cameras[0];
      const project=()=>{const k=projectionCamera?.intrinsics;if(referenceProjection&&k){const n=camera.near;camera.projectionMatrix.makePerspective(-k.cx*n/k.fx,(k.width-k.cx)*n/k.fx,k.cy*n/k.fy,-(k.height-k.cy)*n/k.fy,n,camera.far);camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();}else camera.updateProjectionMatrix();};
      const frame=()=>{referenceProjection=false;project();camera.up.set(0,-1,0);controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(radius,-radius*.6,-radius));controls.update();};reset.current=frame;
      wholeRoute.current=()=>{referenceProjection=false;project();pathGroup.visible=true;setShowPath(true);camera.up.set(0,-1,0);controls.target.copy(fullCenter);camera.position.copy(fullCenter).add(new THREE.Vector3(fullRadius,-fullRadius*.6,-fullRadius));controls.update();};
      const fromRecording=(index:number)=>{
        const first=geometry.cameras[Math.max(0,Math.min(index,geometry.cameras.length-1))],pose=first?.camera_to_world;if(!pose){frame();return;}
        projectionCamera=first;setRecordedSeconds(first.ticks_90k/90000);
        setRecordedImage((first as typeof first&{image:string}).image);
        const distance=Math.max(new THREE.Box3().setFromPoints(centers).getSize(new THREE.Vector3()).length()*.15,.05);
        referenceProjection=true;project();camera.position.set(...first.center as [number,number,number]);camera.up.set(-pose[0][1],-pose[1][1],-pose[2][1]);
        controls.target.copy(camera.position).add(new THREE.Vector3(pose[0][2],pose[1][2],pose[2][2]).multiplyScalar(distance));controls.update();
      };recordedView.current=fromRecording;setCameraCount(geometry.cameras.length);setRecordedIndex(0);fromRecording(0);
      const resize=()=>{const k=geometry.cameras[0]?.intrinsics,aspect=k?k.width/k.height:16/9;const width=Math.min(element.clientWidth,element.clientHeight*aspect),height=width/aspect;renderer.setSize(width,height);camera.aspect=aspect;project();};
      const observer=new ResizeObserver(resize);observer.observe(element);resize();
      renderer.setAnimationLoop(()=>{controls.update();renderer.render(scene,camera);});
      dispose=()=>{pointObject.current=null;lineObject.current=null;reset.current=()=>{};wholeRoute.current=()=>{};recordedView.current=()=>{};styleRef.current=()=>{};observer.disconnect();renderer.setAnimationLoop(null);controls.dispose();for(const object of objects)object.dispose();renderer.dispose();renderer.domElement.remove();};
      setDetails(`${geometry.cameras.length} камер · ${points.length.toLocaleString('ru')} опорных точек · путь камеры ${geometry.camera_path_units.toFixed(2)} усл. ед.`);
      if(representation==='surface'&&latestStatus.current.surface?.available){
        setDetails('Загружаем и проверяем текстурированную 3D-модель…');
        const payload=await loadSurface(job,latestStatus.current.surface,abort.signal);if(retired)return;
        const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');if(retired)return;
        const gltf=await new GLTFLoader().parseAsync(payload,'');
        const geometries=new Set<BufferGeometry>(),materials=new Set<Material>(),textures=new Set<Texture>();
        const meshes:{mesh:Mesh;original:Material|Material[]}[]=[];
        gltf.scene.traverse(object=>{if(object instanceof THREE.Mesh){geometries.add(object.geometry);const original=object.material;meshes.push({mesh:object,original});for(const material of Array.isArray(original)?original:[original]){materials.add(material);for(const value of Object.values(material))if(value instanceof THREE.Texture)textures.add(value);}object.geometry.computeVertexNormals();}});
        const release=()=>{for(const item of geometries)item.dispose();for(const item of materials)item.dispose();for(const item of textures){item.dispose();const source=item.source.data as {close?:()=>void}|undefined;source?.close?.();}};
        if(retired){release();return;}objects.push({dispose:release});scene.add(gltf.scene);
        const solid=new THREE.MeshStandardMaterial({color:'#9bb7c7',roughness:.85,metalness:0,side:THREE.DoubleSide}),normal=new THREE.MeshNormalMaterial({side:THREE.DoubleSide}),wire=new THREE.MeshBasicMaterial({color:'#67e8c7',wireframe:true,side:THREE.DoubleSide});
        objects.push(solid,normal,wire);scene.add(new THREE.HemisphereLight('#e1f4ff','#34405a',2.4));
        const light=new THREE.DirectionalLight('#ffffff',2);light.position.set(-5,-8,-3);scene.add(light);
        styleRef.current=value=>{for(const entry of meshes)entry.mesh.material=value==='texture'?entry.original:value==='solid'?solid:value==='normal'?normal:wire;};styleRef.current(style.current);
        const surfaceBounds=new THREE.Box3().setFromObject(gltf.scene);surfaceBounds.getCenter(center);radius=Math.max(surfaceBounds.getSize(new THREE.Vector3()).length()*.45,.1);
        setDetails(`${latestStatus.current.surface.result?.triangles.toLocaleString('ru')} треугольников · ${geometry.cameras.length} ракурсов · текстурированная модель`);
      }else if(status.dense_available||status.dense_partial_available){
        const {SparkRenderer,SplatMesh}=await import('@sparkjsdev/spark');
        if(retired)return;
        const spark=new SparkRenderer({renderer});scene.add(spark);objects.push(spark);
        const splat=new SplatMesh({url:`http://127.0.0.1:3342/jobs/${job.id}/scene`,requestHeader:{'X-Sphere-Reconstruction':'1','X-Job-Key':job.key},maxSplats:750000,lod:false});
        objects.push(splat);await splat.initialized;
        if(retired)return;scene.add(splat);
        setDetails(`${geometry.cameras.length} камер · ${status.dense_partial_available?'промежуточная':'плотная'} Gaussian-сцена · путь камеры ${geometry.camera_path_units.toFixed(2)} усл. ед.`);
      }
    })().catch(e=>{if(!retired){dispose();dispose=()=>{};setError(e instanceof Error?e.message:'Не удалось открыть сцену.');}});
    return()=>{retired=true;abort.abort();dispose();};
  },[job,status.dense_available,status.dense_partial_available,representation,surfaceReady,surfaceHash,surfaceIdentity]);
  const download=async()=>{
    if(!status.surface||downloading)return;setDownloading(true);
    try{const body=await loadSurface(job,status.surface);const url=URL.createObjectURL(new Blob([body],{type:'model/gltf-binary'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`sphere-route-${job.id.slice(0,8)}.glb`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(e){setError(e instanceof Error?e.message:'Не удалось скачать модель.');}finally{setDownloading(false);}
  };
  const fullscreen=async()=>{try{if(document.fullscreenElement===panel.current)await document.exitFullscreen();else if(panel.current?.requestFullscreen)await panel.current.requestFullscreen();else setError('Полноэкранный просмотр в этом браузере недоступен.');}catch{setError('Не удалось открыть полноэкранный просмотр.');}};
  return <div ref={panel} className={`overflow-hidden rounded-xl border border-border bg-background ${expanded?'flex h-full flex-col':''}`}>
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-gradient-to-r from-sky-500/10 to-emerald-500/5 px-4 py-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Представление сцены"><Button size="sm" variant={representation==='surface'?'default':'outline'} disabled={!surfaceReady} onClick={()=>setRepresentation('surface')}>3D-модель</Button><Button size="sm" variant={representation==='gaussian'?'default':'outline'} onClick={()=>setRepresentation('gaussian')}>Визуальная сцена</Button></div>
      <div className="flex gap-2"><Button size="sm" variant="outline" onClick={()=>{void fullscreen();}}>{expanded?'Свернуть':'Развернуть'}</Button>{surfaceReady&&<Button size="sm" variant="outline" disabled={downloading} onClick={()=>{void download();}}>{downloading?'Проверка…':'Скачать GLB'}</Button>}</div>
    </div>
    {representation==='surface'&&<div className="flex flex-wrap gap-2 border-b border-border px-4 py-2" role="group" aria-label="Отображение поверхностей">{([['texture','Текстуры'],['solid','Поверхности'],['normal','Нормали'],['wire','Каркас']] as const).map(([value,label])=><Button key={value} size="sm" variant={surfaceStyle===value?'secondary':'ghost'} aria-pressed={surfaceStyle===value} onClick={()=>{setSurfaceStyle(value);styleRef.current(value);}}>{label}</Button>)}</div>}
    {coverage&&<div className="space-y-2 border-b border-border bg-sky-500/5 px-4 py-3"><p className="text-sm font-medium">{representation==='surface'?'Выбранный фрагмент':'Запись'}: {coverage.first.toFixed(1)}–{coverage.last.toFixed(1)} с · {coverage.views}/{coverage.totalViews} ракурсов</p><div className="relative h-2 overflow-hidden rounded-full bg-muted" aria-label="Интервал фрагмента в исходной записи"><div className="absolute inset-y-0 rounded-full bg-emerald-400" style={{left:`${coverage.sourceEnd>coverage.sourceStart?(coverage.first-coverage.sourceStart)/(coverage.sourceEnd-coverage.sourceStart)*100:0}%`,width:`${coverage.fraction*100}%`}}/></div><p className="text-xs text-muted-foreground">Вся запись: {(coverage.sourceEnd-coverage.sourceStart).toFixed(1)} с. Выбранные соседние ракурсы охватывают {(coverage.fraction*100).toFixed(1)}% её времени. Это не процент точной геометрии.</p></div>}
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"><p className="text-xs text-muted-foreground">{details}</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={()=>recordedView.current(recordedIndex)}>Камера прохода</Button><Button size="sm" variant="outline" onClick={()=>reset.current()}>{representation==='surface'?'Вписать фрагмент':'Вписать сцену'}</Button><Button size="sm" variant="outline" onClick={()=>wholeRoute.current()}>Весь путь камеры</Button></div></div>
    {cameraCount>0&&<label className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3 text-xs text-muted-foreground"><span>Ракурс прохода {recordedIndex+1}/{cameraCount} · {recordedSeconds.toFixed(1)} с</span><input className="min-w-40 flex-1 accent-emerald-500" aria-label="Ракурс записанного прохода" type="range" min={0} max={cameraCount-1} step={1} value={recordedIndex} onChange={e=>{const index=Number(e.target.value);setRecordedIndex(index);recordedView.current(index);}}/></label>}
    <div className="flex flex-wrap gap-4 border-t border-border px-4 py-2 text-xs text-muted-foreground"><label className="flex items-center gap-2"><input type="checkbox" checked={showPoints} onChange={e=>{setShowPoints(e.target.checked);if(pointObject.current)pointObject.current.visible=e.target.checked;}}/>Опорные точки поверх сцены</label><label className="flex items-center gap-2"><input type="checkbox" checked={showPath} onChange={e=>{setShowPath(e.target.checked);if(lineObject.current)lineObject.current.visible=e.target.checked;}}/>Траектория камеры</label></div>
    <div ref={host} className={`flex w-full items-center justify-center bg-black ${expanded?'min-h-0 flex-1':'h-[480px]'}`} aria-label="Восстановленная 3D-сцена" />
    {recordedImage&&<details className="border-t border-border" open={compareSource} onToggle={event=>setCompareSource(event.currentTarget.open)}><summary className="cursor-pointer px-4 py-3 text-xs">Сравнить с исходным кадром текущего ракурса · {recordedSeconds.toFixed(1)} с</summary>{compareSource&&<RecordedSourceFrame job={job} image={recordedImage}/>}</details>}
    {error&&<p role="alert" className="px-4 py-2 text-sm text-destructive">{error}</p>}
    <p className="px-4 py-3 text-xs leading-5 text-muted-foreground">Левая кнопка — вращать · правая — перемещать · колесо — приближать. Зелёная линия — восстановленный путь камеры. {representation==='surface'&&'Чёрные области не наблюдались достаточно надёжно и не достроены. '}Масштаб в метрах и проходимость не подтверждены.</p>
  </div>;
}
