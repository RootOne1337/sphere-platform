'use client';
import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
import type {BufferGeometry,Material,Mesh,Texture} from 'three';
import {loadSurface} from './surfaceAsset';
import RecordedSourceFrame from './RecordedSourceFrame';
import RouteGeometryMap from './RouteGeometryMap';
import {nearestRouteCamera,readImportedRouteGeometry,routeSourceMatches,type RouteMapCamera} from './routeMapProjection';
import {cameraMotionRequiresReview} from './routePreparation';
import {readSceneGeometrySelection,sceneCameraCoverage,sceneCameraPath,type SceneGeometrySelection} from './sceneGeometrySelection';

type SurfaceStyle='texture'|'solid'|'normal'|'wire';
type Geometry={cameras:RouteMapCamera[];points:number[][];camera_path_units:number;source_manifest_sha256?:string};
type Representation='geometry'|'primary'|'surface'|'gaussian';

export default function ReconstructedScene({job,status,sourceManifestSha=null,selectedTicks=null,onSeekCamera,validTicks,sourcePreview,showGeometryMap=true,selectedGeometry,sourceKey}:{job:ReconstructionJob;status:ReconstructionState;sourceManifestSha?:string|null;selectedTicks?:number|null;onSeekCamera?:(ticks:number)=>void;validTicks?:ReadonlySet<number>;sourcePreview?:ReactNode;showGeometryMap?:boolean;selectedGeometry?:SceneGeometrySelection|null;sourceKey?:string}) {
  const host=useRef<HTMLDivElement>(null),reset=useRef<()=>void>(()=>{}),recordedView=useRef<(index:number)=>void>(()=>{});
  const wholeRoute=useRef<()=>void>(()=>{});
  const [coverage,setCoverage]=useState<ReturnType<typeof sceneCameraCoverage>>(null),[recordedImage,setRecordedImage]=useState(''),[compareSource,setCompareSource]=useState(false);
  const [mapGeometry,setMapGeometry]=useState<Pick<Geometry,'cameras'|'points'|'source_manifest_sha256'>|null>(null);
  const panel=useRef<HTMLDivElement>(null),[expanded,setExpanded]=useState(false);
  useEffect(()=>{const update=()=>setExpanded(document.fullscreenElement===panel.current);document.addEventListener('fullscreenchange',update);return()=>document.removeEventListener('fullscreenchange',update);},[]);
  const pointObject=useRef<{visible:boolean}|null>(null),lineObject=useRef<{visible:boolean}|null>(null);
  const sparseOnly=!status.dense_available&&!status.dense_partial_available&&!status.surface?.available;
  const selectionProvided=selectedGeometry!==undefined;
  const historicalAllowed=!selectionProvided||selectedGeometry?.id==='primary';
  const [showPoints,setShowPoints]=useState(selectionProvided||sparseOnly),[showPath,setShowPath]=useState(selectionProvided||sparseOnly);
  const [recordedIndex,setRecordedIndex]=useState(0),[cameraCount,setCameraCount]=useState(0),[recordedSeconds,setRecordedSeconds]=useState(0);
  const choiceKey=JSON.stringify([sourceKey,job.id,job.key,sourceManifestSha,selectionProvided,selectedGeometry?.id,selectedGeometry?.sourceKey,selectedGeometry?.jobId,selectedGeometry?.sourceManifestSha]);
  const [viewChoice,setViewChoice]=useState<{key:string;mode:Representation}|null>(null);
  const representation:Representation=viewChoice?.key===choiceKey?viewChoice.mode:selectionProvided?'geometry':status.surface?.available?'surface':status.dense_available||status.dense_partial_available?'gaussian':'primary';
  const setRepresentation=(mode:Representation)=>setViewChoice({key:choiceKey,mode});
  const [surfaceStyle,setSurfaceStyle]=useState<SurfaceStyle>('texture'),[downloading,setDownloading]=useState(false);
  const styleRef=useRef<(value:SurfaceStyle)=>void>(()=>{}),style=useRef(surfaceStyle);style.current=surfaceStyle;
  const surfaceReady=status.surface?.available===true,surfaceHash=status.surface?.result?.sha256;
  const surfaceIdentity=status.surface?.id;
  const latestStatus=useRef(status);latestStatus.current=status;
  const activeIdentity=useMemo(()=>({}),[choiceKey,selectedGeometry?.geometry,selectedGeometry?.recordingRange?.firstTicks,selectedGeometry?.recordingRange?.lastTicks,selectedGeometry?.recordingRange?.frames,validTicks,representation,surfaceReady,surfaceHash,surfaceIdentity,status.dense_available,status.dense_partial_available]);
  const [readyIdentity,setReadyIdentity]=useState<object|null>(null),[viewCameras,setViewCameras]=useState<RouteMapCamera[]>([]);
  const currentReady=readyIdentity===activeIdentity;
  const ticksRef=useRef(selectedTicks);ticksRef.current=selectedTicks;
  const identityRef=useRef(activeIdentity);identityRef.current=activeIdentity;
  const downloadAbort=useRef<AbortController|null>(null);
  const options=useRef({points:sparseOnly,path:sparseOnly});options.current={points:showPoints,path:showPath};
  const [error,setError]=useState<string|null>(null),[errorIdentity,setErrorIdentity]=useState<object|null>(null),[details,setDetails]=useState('Загружаем восстановленные камеры…'),[detailsIdentity,setDetailsIdentity]=useState<object|null>(null);
  useEffect(()=>{
    let retired=false,dispose=()=>{};const abort=new AbortController();setError(null);setMapGeometry(null);setReadyIdentity(null);setCameraCount(0);setCoverage(null);setRecordedImage('');setViewCameras([]);setCompareSource(false);
    setDetailsIdentity(activeIdentity);setDownloading(false);
    setDetails(representation==='geometry'?'Загружаем выбранную схему…':'Загружаем исторический результат основного расчёта…');
    void(async()=>{
      if(!sourceManifestSha||!validTicks?.size)throw Error('Выберите подтверждённую исходную запись для просмотра геометрии.');
      let parsed;
      if(representation==='geometry'&&selectionProvided){
        if(!selectedGeometry){setDetails('Выберите сохранённую схему ориентиров.');return;}
        parsed=readSceneGeometrySelection(selectedGeometry,{sourceKey,jobId:job.id,sourceManifestSha,validTicks});
        if(!parsed){setDetails('Выбранная схема загружается. Основная геометрия не подставляется.');return;}
      }else{
        const response=await reconstructionRequest(`/jobs/${job.id}/geometry`,job,{signal:abort.signal});
        if(retired)return;const raw:unknown=await response.json();if(retired)return;
        parsed=readImportedRouteGeometry(raw,sourceManifestSha,validTicks);
      }
      const geometry:Geometry={...parsed,camera_path_units:sceneCameraPath(parsed)};
      const [THREE,{OrbitControls}]=await Promise.all([import('three'),import('three/addons/controls/OrbitControls.js')]);
      if(retired)return;
      const allCameras=geometry.cameras;
      setMapGeometry({cameras:geometry.cameras,points:geometry.points,source_manifest_sha256:geometry.source_manifest_sha256});
      if(representation==='surface'&&latestStatus.current.surface?.result){
        const included=new Set(latestStatus.current.surface.result.source_images);geometry.cameras=geometry.cameras.filter(c=>included.has((c as typeof c&{image:string}).image));
        if(!geometry.cameras.length)throw Error('Камеры модели не совпадают с проходом.');
      }
      setCoverage(sceneCameraCoverage(geometry.cameras,selectedGeometry?.recordingRange,validTicks));
      if(retired||!host.current)return;
      const element=host.current,scene=new THREE.Scene();scene.background=new THREE.Color('#080c17');
      const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));element.appendChild(renderer.domElement);
      const camera=new THREE.PerspectiveCamera(55,1,.001,10000);camera.up.set(0,-1,0);
      let controls:InstanceType<typeof OrbitControls>;
      try{controls=new OrbitControls(camera,renderer.domElement);}catch(e){renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();throw e;}
      controls.enableDamping=true;controls.screenSpacePanning=true;
      const objects: {dispose:()=>void}[]=[];const points=geometry.points;let observer:ResizeObserver|undefined;
      dispose=()=>{pointObject.current=null;lineObject.current=null;reset.current=()=>{};wholeRoute.current=()=>{};recordedView.current=()=>{};styleRef.current=()=>{};observer?.disconnect();renderer.setAnimationLoop(null);controls.dispose();for(const object of objects)object.dispose();renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();};
      if(points.length){
        const buffer=new THREE.BufferGeometry();buffer.setAttribute('position',new THREE.Float32BufferAttribute(points.flatMap(p=>p.slice(0,3)),3));
        buffer.setAttribute('color',new THREE.Float32BufferAttribute(points.flatMap(p=>p.slice(3,6).map(c=>c/255)),3));
        const material=new THREE.PointsMaterial({size:2,sizeAttenuation:false,vertexColors:true});
        const cloud=new THREE.Points(buffer,material);cloud.visible=options.current.points;pointObject.current=cloud;
        scene.add(cloud);objects.push(buffer,material);
      }
      const centers=geometry.cameras.map(c=>new THREE.Vector3(...c.center as [number,number,number]));
      const segments=(cameras:Geometry['cameras'])=>cameras.flatMap((camera,index)=>{
        if(!index)return [];const previous=cameras[index-1],dt=(camera.ticks_90k-previous.ticks_90k)/90000;
        return dt>0&&dt<=1?[new THREE.Vector3(...previous.center as [number,number,number]),new THREE.Vector3(...camera.center as [number,number,number])]:[];
      });
      const lineGeometry=new THREE.BufferGeometry().setFromPoints(segments(geometry.cameras)),lineMaterial=new THREE.LineBasicMaterial({color:'#47e6b1',depthTest:false});
      const line=new THREE.LineSegments(lineGeometry,lineMaterial);line.renderOrder=10;
      const contextGeometry=new THREE.BufferGeometry().setFromPoints(segments(allCameras)),contextMaterial=new THREE.LineBasicMaterial({color:'#72859d',depthTest:false,transparent:true,opacity:.55});
      const pathGroup=new THREE.Group();pathGroup.add(new THREE.LineSegments(contextGeometry,contextMaterial),line);pathGroup.visible=options.current.path;lineObject.current=pathGroup;scene.add(pathGroup);objects.push(lineGeometry,lineMaterial,contextGeometry,contextMaterial);
      const bounds=new THREE.Box3().setFromPoints([...centers,...points.filter((_,i)=>i%20===0).map(p=>new THREE.Vector3(...p.slice(0,3) as [number,number,number]))]);
      const center=bounds.getCenter(new THREE.Vector3());let radius=Math.max(bounds.getSize(new THREE.Vector3()).length()*.45,.1);
      const fullBounds=new THREE.Box3().setFromPoints(allCameras.map(c=>new THREE.Vector3(...c.center as [number,number,number]))),fullCenter=fullBounds.getCenter(new THREE.Vector3()),fullRadius=Math.max(fullBounds.getSize(new THREE.Vector3()).length()*.6,.1);
      let referenceProjection=false,projectionCamera=geometry.cameras[0];
      const project=()=>{const k=projectionCamera?.intrinsics;if(referenceProjection&&k){const n=camera.near;camera.projectionMatrix.makePerspective(-k.cx*n/k.fx,(k.width-k.cx)*n/k.fx,k.cy*n/k.fy,-(k.height-k.cy)*n/k.fy,n,camera.far);camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();}else camera.updateProjectionMatrix();};
      const frame=()=>{referenceProjection=false;project();camera.up.set(0,-1,0);controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(radius,-radius*.6,-radius));controls.update();};reset.current=frame;
      wholeRoute.current=()=>{referenceProjection=false;project();pathGroup.visible=true;setShowPath(true);camera.up.set(0,-1,0);controls.target.copy(fullCenter);camera.position.copy(fullCenter).add(new THREE.Vector3(fullRadius,-fullRadius*.6,-fullRadius));controls.update();};
      const fromRecording=(index:number)=>{
        if(retired)return;
        const first=geometry.cameras[Math.max(0,Math.min(index,geometry.cameras.length-1))],pose=first?.camera_to_world;if(!first)return;
        projectionCamera=first;setRecordedSeconds(first.ticks_90k/90000);
        setRecordedImage(first.image??'');
        if(!pose){frame();return;}
        const distance=Math.max(new THREE.Box3().setFromPoints(centers).getSize(new THREE.Vector3()).length()*.15,.05);
        referenceProjection=true;project();camera.position.set(...first.center as [number,number,number]);camera.up.set(-pose[0][1],-pose[1][1],-pose[2][1]);
        controls.target.copy(camera.position).add(new THREE.Vector3(pose[0][2],pose[1][2],pose[2][2]).multiplyScalar(distance));controls.update();
      };recordedView.current=fromRecording;setCameraCount(geometry.cameras.length);setViewCameras(geometry.cameras);
      const initial=ticksRef.current!==null&&validTicks.has(ticksRef.current)?nearestRouteCamera(geometry.cameras,ticksRef.current)??0:0;
      setRecordedIndex(initial);fromRecording(initial);
      const resize=()=>{const k=geometry.cameras[0]?.intrinsics,aspect=k?k.width/k.height:16/9;const width=Math.min(element.clientWidth,element.clientHeight*aspect),height=width/aspect;renderer.setSize(width,height);camera.aspect=aspect;project();};
      observer=new ResizeObserver(resize);observer.observe(element);resize();
      renderer.setAnimationLoop(()=>{controls.update();renderer.render(scene,camera);});
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
      }else if(representation==='gaussian'&&(status.dense_available||status.dense_partial_available)){
        const {SparkRenderer,SplatMesh}=await import('@sparkjsdev/spark');
        if(retired)return;
        const spark=new SparkRenderer({renderer});scene.add(spark);objects.push(spark);
        const splat=new SplatMesh({url:`http://127.0.0.1:3342/jobs/${job.id}/scene`,requestHeader:{'X-Sphere-Reconstruction':'1','X-Job-Key':job.key},maxSplats:750000,lod:false});
        objects.push(splat);await splat.initialized;
        if(retired)return;scene.add(splat);
        setDetails(`${geometry.cameras.length} камер · ${status.dense_partial_available?'промежуточная':'плотная'} Gaussian-сцена · путь камеры ${geometry.camera_path_units.toFixed(2)} усл. ед.`);
      }
      if(!retired)setReadyIdentity(activeIdentity);
    })().catch(e=>{if(!retired){dispose();dispose=()=>{};setErrorIdentity(activeIdentity);setError(e instanceof Error?e.message:'Не удалось открыть сцену.');}});
    return()=>{retired=true;abort.abort();downloadAbort.current?.abort();dispose();};
  },[activeIdentity]);
  useEffect(()=>{
    if(!currentReady||selectedTicks===null||!validTicks?.has(selectedTicks))return;
    const index=nearestRouteCamera(viewCameras,selectedTicks);if(index===null)return;
    setRecordedIndex(index);recordedView.current(index);
  },[currentReady,selectedTicks,validTicks,viewCameras]);
  const download=async()=>{
    if(!status.surface||downloading||representation!=='surface')return;setDownloading(true);const identity=activeIdentity,abort=new AbortController();downloadAbort.current=abort;
    try{const body=await loadSurface(job,status.surface,abort.signal);if(identityRef.current!==identity||abort.signal.aborted)return;const url=URL.createObjectURL(new Blob([body],{type:'model/gltf-binary'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`sphere-primary-${job.id.slice(0,8)}.glb`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(e){if(identityRef.current===identity){setErrorIdentity(identity);setError(e instanceof Error?e.message:'Не удалось скачать модель.');}}finally{if(identityRef.current===identity)setDownloading(false);}
  };
  const fullscreen=async()=>{try{if(document.fullscreenElement===panel.current)await document.exitFullscreen();else if(panel.current?.requestFullscreen)await panel.current.requestFullscreen();else{setErrorIdentity(activeIdentity);setError('Полноэкранный просмотр в этом браузере недоступен.');}}catch{if(identityRef.current===activeIdentity){setErrorIdentity(activeIdentity);setError('Не удалось открыть полноэкранный просмотр.');}}};
  const historical=representation!=='geometry';
  return <div ref={panel} className={`overflow-hidden rounded-xl border border-border bg-background ${expanded?'flex h-full flex-col':''}`}>
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-gradient-to-r from-sky-500/10 to-emerald-500/5 px-4 py-3">
      <div className="space-y-1"><Button size="sm" variant={!historical?'default':'outline'} onClick={()=>setRepresentation(selectionProvided?'geometry':'primary')}>Камеры и точки{selectionProvided?' выбранной схемы':''}</Button>
        <p className="text-xs text-muted-foreground">{historical?'Исторический результат основного расчёта · отдельная геометрия':selectedGeometry?.label||'Выбранная схема ориентиров'}</p></div>
      <div className="flex gap-2"><Button size="sm" variant="outline" onClick={()=>{void fullscreen();}}>{expanded?'Свернуть':'Развернуть'}</Button>{representation==='surface'&&surfaceReady&&<Button size="sm" variant="outline" disabled={downloading} onClick={()=>{void download();}}>{downloading?'Проверка…':'Скачать GLB основного расчёта'}</Button>}</div>
    </div>
    {historicalAllowed&&<details className="border-b border-border px-4 py-2"><summary className="cursor-pointer text-xs text-muted-foreground">Другие представления основного расчёта</summary><div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Исторические представления основного расчёта">
      <Button size="sm" variant={representation==='primary'?'secondary':'outline'} disabled={!status.geometry_available} onClick={()=>setRepresentation('primary')}>Основной расчёт · камеры и точки</Button>
      <Button size="sm" variant={representation==='surface'?'secondary':'outline'} disabled={!surfaceReady} onClick={()=>setRepresentation('surface')}>Основной расчёт · 3D-модель</Button>
      <Button size="sm" variant={representation==='gaussian'?'secondary':'outline'} disabled={!status.dense_available&&!status.dense_partial_available} onClick={()=>setRepresentation('gaussian')}>Основной расчёт · Gaussian-сцена</Button>
    </div><p className="mt-2 text-xs text-muted-foreground">Эти результаты используют геометрию выбранного основного расчёта; отдельные поверхности могут покрывать только часть ракурсов.</p></details>}
    {!historical&&selectedGeometry?.diagnostic&&<p className="border-b border-border px-4 py-2 text-xs text-amber-700 dark:text-amber-300">Диагностическая схема · {selectedGeometry.id}. Масштаб, положение транспорта и допуск к движению не подтверждены.</p>}
    {representation==='surface'&&<div className="flex flex-wrap gap-2 border-b border-border px-4 py-2" role="group" aria-label="Отображение поверхностей">{([['texture','Текстуры'],['solid','Поверхности'],['normal','Нормали'],['wire','Каркас']] as const).map(([value,label])=><Button key={value} size="sm" variant={surfaceStyle===value?'secondary':'ghost'} aria-pressed={surfaceStyle===value} onClick={()=>{setSurfaceStyle(value);styleRef.current(value);}}>{label}</Button>)}</div>}
    {currentReady&&coverage&&<div className="space-y-2 border-b border-border bg-sky-500/5 px-4 py-3"><p className="text-sm font-medium">Камеры схемы: {coverage.first.toFixed(1)}–{coverage.last.toFixed(1)} с · {coverage.views} ракурсов</p>{coverage.knownSource?<><div className="relative h-2 overflow-hidden rounded-full bg-muted" aria-label="Интервал камер в исходной записи"><div className="absolute inset-y-0 rounded-full bg-emerald-400" style={{left:`${coverage.sourceEnd>coverage.sourceStart?(coverage.first-coverage.sourceStart)/(coverage.sourceEnd-coverage.sourceStart)*100:0}%`,width:`${coverage.sourceEnd>coverage.sourceStart?(coverage.last-coverage.first)/(coverage.sourceEnd-coverage.sourceStart)*100:0}%`}}/></div><p className="text-xs text-muted-foreground">Вся исходная запись: {coverage.sourceStart.toFixed(1)}–{coverage.sourceEnd.toFixed(1)} с. Интервалы соседних камер: {(coverage.fraction*100).toFixed(1)}% времени; без начала {coverage.uncoveredStart.toFixed(1)} с, без конца {coverage.uncoveredEnd.toFixed(1)} с, внутренних разрывов {coverage.gapSeconds.toFixed(1)} с. Это не процент точной геометрии.</p></>:<p className="text-xs text-muted-foreground">Показан интервал зарегистрированных камер. Полный временной интервал исходной записи не подтверждён.</p>}</div>}
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"><p className="text-xs text-muted-foreground">{errorIdentity===activeIdentity&&error?'3D-просмотр недоступен.':detailsIdentity===activeIdentity?details:'Загружаем выбранную схему…'}</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={!currentReady} onClick={()=>recordedView.current(recordedIndex)}>Камера прохода</Button><Button size="sm" variant="outline" disabled={!currentReady} onClick={()=>reset.current()}>{representation==='surface'?'Вписать фрагмент':'Вписать сцену'}</Button><Button size="sm" variant="outline" disabled={!currentReady} onClick={()=>wholeRoute.current()}>Весь путь камеры</Button></div></div>
    {currentReady&&cameraCount>0&&<label className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3 text-xs text-muted-foreground"><span>Ракурс прохода {recordedIndex+1}/{cameraCount} · {recordedSeconds.toFixed(1)} с</span><input className="min-w-40 flex-1 accent-emerald-500" aria-label="Ракурс записанного прохода" type="range" min={0} max={cameraCount-1} step={1} value={recordedIndex} onChange={e=>{const index=Number(e.target.value),camera=viewCameras[index];if(!camera||!validTicks?.has(camera.ticks_90k))return;setRecordedIndex(index);recordedView.current(index);onSeekCamera?.(camera.ticks_90k);}}/></label>}
    <div className="flex flex-wrap gap-4 border-t border-border px-4 py-2 text-xs text-muted-foreground"><label className="flex items-center gap-2"><input type="checkbox" checked={showPoints} onChange={e=>{setShowPoints(e.target.checked);if(pointObject.current)pointObject.current.visible=e.target.checked;}}/>Опорные точки поверх сцены</label><label className="flex items-center gap-2"><input type="checkbox" checked={showPath} onChange={e=>{setShowPath(e.target.checked);if(lineObject.current)lineObject.current.visible=e.target.checked;}}/>Траектория камеры</label></div>
    <div ref={host} style={{visibility:currentReady?'visible':'hidden'}} className={`flex w-full items-center justify-center bg-black ${expanded?'min-h-0 flex-1':'h-[480px]'}`} aria-label="Восстановленная 3D-сцена" />
    {currentReady&&showGeometryMap&&mapGeometry&&<RouteGeometryMap cameras={mapGeometry.cameras} points={mapGeometry.points} motionWarning={(!historical&&!!selectedGeometry?.diagnostic)||cameraMotionRequiresReview(status.camera_motion)} diagnosticId={!historical&&selectedGeometry?.diagnostic?selectedGeometry.id:undefined} selectedTicks={selectedTicks} validTicks={routeSourceMatches(sourceManifestSha,mapGeometry.source_manifest_sha256)?validTicks:undefined} onSeekCamera={routeSourceMatches(sourceManifestSha,mapGeometry.source_manifest_sha256)?onSeekCamera:undefined} sourcePreview={sourcePreview}/>}
    {currentReady&&(recordedImage||sourcePreview)&&<details className="border-t border-border" open={compareSource} onToggle={event=>setCompareSource(event.currentTarget.open)}><summary className="cursor-pointer px-4 py-3 text-xs">{historical?'Исходный кадр камеры':'Выбранный исходный кадр записи'} · {(!historical&&selectedTicks!==null?selectedTicks/90000:recordedSeconds).toFixed(1)} с</summary>{compareSource&&(!historical?sourcePreview:recordedImage?<RecordedSourceFrame key={`${job.id}:${recordedImage}`} job={job} image={recordedImage}/>:sourcePreview)}</details>}
    {errorIdentity===activeIdentity&&error&&<p role="alert" className="px-4 py-2 text-sm text-destructive">{error}</p>}
    <p className="px-4 py-3 text-xs leading-5 text-muted-foreground">Левая кнопка — вращать · правая — перемещать · колесо — приближать. Зелёная линия — восстановленный путь камеры; разрывы больше секунды не соединяются. {representation==='surface'&&'Чёрные области не наблюдались достаточно надёжно и не достроены. '}Масштаб в метрах и проходимость не подтверждены.</p>
  </div>;
}
