'use client';
import dynamic from 'next/dynamic';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Box,Loader2} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {processingSurface,reconstructionRequest,terminalReconstruction,uploadReconstruction,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
import {listReconstructionLinks,readReconstructionLink,saveReconstructionLink,validReconstructionJob} from './reconstructionLink';
import ReferenceComparison from './ReferenceComparison';
import {cameraMotionRequiresReview,navigationErrorLabel,navigationPhaseLabel,routeCoverageLabel,prepareRoute as prepareRouteIntent,preparationError,preparationQuotaReached} from './routePreparation';
const Scene=dynamic(()=>import('./ReconstructedScene'),{ssr:false,loading:()=> <p>Загружаем 3D-просмотр…</p>});
const phases:Record<string,string>={uploading:'Передача сохранённой записи',starting:'Запуск обработчика',verifying:'Проверка исходника и освобождения ввода',extracting:'Извлечение кадров в исходном разрешении',features:'Поиск устойчивых визуальных признаков',matching:'Сопоставление соседних ракурсов',cameras:'Восстановление связанных камер',training:'Построение плотной Gaussian-сцены на GPU',complete:'Плотная сцена готова',failed:'Обработка остановлена',cancelled:'Задание отменено'};
const reasons:Record<string,string>={no_connected_cameras_need_translation_and_overlap:'Не удалось связать камеры. Нужен проход с перемещением, перекрывающимися ракурсами и неподвижными деталями.',camera_quality_gate_failed:'Камеры восстановлены лишь частично или с большой ошибкой. Результат не принят как цельная сцена.',resource_guard:'Недостаточно ресурсов для безопасного продолжения.',worker_service_restarted:'Сервис был перезапущен. Исходная запись сохранена.',brush_failed_see_local_log:'Плотный рендер завершился с ошибкой. Камеры можно проверить отдельно.'};
reasons.brush_timing_overflow='Brush завершился с ошибкой измерения времени GPU. Камеры и проверенные промежуточные результаты сохранены.';
reasons.brush_system_timing_build_required='Совместимый локальный движок плотной сцены ещё не подготовлен. Запись и восстановленные камеры сохранены.';
phases.complete='Реконструкция рассчитана · базовая проверка ракурсов пройдена';
phases.sparse_complete='Камеры и опорные точки рассчитаны';
phases.evaluating='Сравнение рендера с исходными ракурсами';
phases.quality_rejected='Реконструкция не прошла проверку качества';
phases.review_required='Расчёт завершён · качество ещё не проверено';
phases.partial_scene='Построен фрагмент сцены · часть ракурсов не связана';
reasons.camera_geometry_degenerate='Геометрия не прошла проверку вырождения или сильных выбросов камер. Маленькая ошибка проекции здесь недостаточна; плотный этап остановлен.';
reasons.camera_intrinsics_degenerate='Расчёт дал некорректные параметры камеры. Низкая ошибка проекции не подтверждает правильность сцены; исходная запись сохранена.';
reasons.dense_visual_quality_gate_failed='Рендер недостаточно совпадает с исходными ракурсами. Эта сцена не принята как качественный результат.';
reasons.lightglue_weights_mismatch='Файл модели сопоставления не прошёл проверку целостности. Обработка остановлена.';
reasons.lightglue_source_mismatch='Версия локального инструмента сопоставления не совпадает с проверенной.';
reasons.lightglue_gpu_unavailable='GPU для сопоставления ракурсов недоступен. Запись сохранена.';
reasons.learned_matching_timeout='Сопоставление ракурсов достигло лимита времени. Промежуточные материалы сохранены.';
reasons.reference_evaluation_failed='Не удалось завершить проверку рендера по исходным ракурсам. Качество не подтверждено.';
export function TeachingReconstruction({clip,scope,folder,complete,hudHidden=false,onBusyChange,onRouteChange,visible=true,sourceManifestSha=null,selectedTicks=null,onSeekCamera,validTicks,sourcePreview,alternativeCameraCount=null}:{clip:string;scope:string;folder:()=>FileSystemDirectoryHandle|null;complete:boolean;hudHidden?:boolean;onBusyChange:(busy:boolean)=>void;onRouteChange?:(job:ReconstructionJob|null)=>void;visible?:boolean;sourceManifestSha?:string|null;selectedTicks?:number|null;onSeekCamera?:(ticks:number)=>void;validTicks?:ReadonlySet<number>;sourcePreview?:ReactNode;alternativeCameraCount?:number|null}) {
  const [job,setJob]=useState<ReconstructionJob|null>(null),[status,setStatus]=useState<ReconstructionState|null>(null),[error,setError]=useState<string|null>(null);
  const [attempts,setAttempts]=useState<ReconstructionJob[]>([]),[switchingAttempt,setSwitchingAttempt]=useState(false);
  const [preparationNotice,setPreparationNotice]=useState<{jobId:string;message:string}|null>(null),[quotaJob,setQuotaJob]=useState<string|null>(null);
  const [mask,setMask]=useState(hudHidden?'none':'game'),[steps,setSteps]=useState(30000),[progress,setProgress]=useState('');
  const [uploading,setUploading]=useState(false);const uploadAbort=useRef<AbortController|null>(null);
  const [recovering,setRecovering]=useState(true);const folderRef=useRef(folder);folderRef.current=folder;
  const [refresh,setRefresh]=useState(0),[surfaceStarting,setSurfaceStarting]=useState(false);
  const [firstView,setFirstView]=useState(0),[viewCount,setViewCount]=useState(18);
  const [selectedFragment,setSelectedFragment]=useState('legacy');
  const models=[...(status?.surface?[status.surface]:[]),...status?.fragments??[]].sort((a,b)=>(a.fragment?.first_view??0)-(b.fragment?.first_view??0));
  const selectedModel=models.find(item=>(item.id??'legacy')===selectedFragment&&item.available)??models.find(item=>item.available);
  const workingSurface=status?processingSurface(status):undefined;
  const storageKey=`sphere-reconstruction-${scope}-${clip}`;
  const busy=recovering||uploading||surfaceStarting||switchingAttempt||!!job&&(!status||!terminalReconstruction(status));
  useEffect(()=>{onBusyChange(busy);},[busy,onBusyChange]);
  useEffect(()=>{onRouteChange?.(job);},[job,onRouteChange]);
  useEffect(()=>()=>{uploadAbort.current?.abort();onBusyChange(false);},[onBusyChange]);
  useEffect(()=>{
    let retired=false;setRecovering(true);
    void(async()=>{
      const source=folderRef.current();let saved=source?await readReconstructionLink(source,clip):null;
      if(!saved){const previous=JSON.parse(sessionStorage.getItem(storageKey)??'null');if(validReconstructionJob(previous)){saved=previous;if(source)await saveReconstructionLink(source,clip,saved);}}
      const available=source?await listReconstructionLinks(source,clip):saved?[saved]:[];
      if(!retired){setAttempts(available);if(saved)setJob(current=>current??saved);setRecovering(false);}
    })().catch(()=>{if(!retired){setError('Не удалось восстановить локальную ссылку на сцену. Исходная запись сохранена.');setRecovering(false);}});
    return()=>{retired=true;};
  },[storageKey,clip]);
  useEffect(()=>{
    if(!job)return;let retired=false;let timer:ReturnType<typeof setTimeout>;const abort=new AbortController();
    const poll=async()=>{try{const next=await(await reconstructionRequest(`/jobs/${job.id}`,job,{signal:abort.signal})).json();if(retired)return;setStatus(next);setError(null);if(!terminalReconstruction(next))timer=setTimeout(()=>{void poll();},2500);}
      catch(e){if(!retired){setError(e instanceof Error&&e.message==='job_not_found'?'Создание задания ещё не подтверждено. Можно продолжить подготовку с тем же идентификатором; обучение повторно не запускается.':`Локальный обработчик не ответил: ${e instanceof Error?e.message:'ошибка'}. Задание не повторялось.`);timer=setTimeout(()=>{void poll();},10000);}}};
    void poll();return()=>{retired=true;abort.abort();clearTimeout(timer);};
  },[job,refresh]);
  const start=async(routeOnly=false)=>{
    const source=folder();if(!source||uploadAbort.current)return;
    const controller=new AbortController();uploadAbort.current=controller;setUploading(true);setError(null);
    let pending:ReconstructionJob|null=job;
    try{
      const next=job??{id:crypto.randomUUID().replaceAll('-',''),key:Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join('')};
      await saveReconstructionLink(source,clip,next);pending=next;setAttempts(await listReconstructionLinks(source,clip));sessionStorage.setItem(storageKey,JSON.stringify(next));
      const created=await(await reconstructionRequest('/jobs',null,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...next,mask,steps,prepare_route:true,route_only:routeOnly}),signal:controller.signal})).json();setStatus(created);setJob(next);
      if(created.phase!=='uploading')return;
      await uploadReconstruction(source,next,(bytes,total)=>setProgress(`${(bytes/1048576).toFixed(1)} / ${(total/1048576).toFixed(1)} МБ`),controller.signal);
      const started=await(await reconstructionRequest(`/jobs/${next.id}/start`,next,{method:'POST',body:'{}',signal:controller.signal})).json();setStatus(started);
    }catch(e){if(pending){setJob(pending);setError(`Запуск не подтверждён: ${e instanceof Error?e.message:'нет ответа'}. Проверяем существующее задание; повторного запуска нет.`);}else setError('Не удалось сохранить ссылку на новое задание. Обработка не запускалась; прежняя попытка и исходная запись сохранены.');}
    finally{uploadAbort.current=null;setUploading(false);}
  };
  const selectAttempt=async(id:string)=>{
    const source=folder(),selected=attempts.find(item=>item.id===id);
    if(!source||!selected||busy||id===job?.id)return;
    setSwitchingAttempt(true);setError(null);
    try{
      await saveReconstructionLink(source,clip,selected);
      sessionStorage.setItem(storageKey,JSON.stringify(selected));
      setStatus(null);setJob(selected);
    }catch{setError('Не удалось выбрать сохранённую попытку. Предыдущие ссылки и исходная запись сохранены.');}
    finally{setSwitchingAttempt(false);}
  };
  const cancel=async()=>{
    uploadAbort.current?.abort();if(!job)return;
    const surface=status?processingSurface(status):undefined;
    try{setStatus(await(await reconstructionRequest(`/jobs/${job.id}/${surface?(surface.id?`fragments/${surface.id}/cancel`:'surface/cancel'):'cancel'}`,job,{method:'POST',body:'{}'})).json());setRefresh(n=>n+1);}catch{setError('Отмена не подтверждена. Состояние проверяется; управление остаётся заблокировано.');setRefresh(n=>n+1);}
  };
  const startSurface=async()=>{
    if(!job||surfaceStarting)return;setSurfaceStarting(true);setError(null);
    try{const id=crypto.randomUUID().replaceAll('-','');setStatus(await(await reconstructionRequest(`/jobs/${job.id}/fragments/${id}/start`,job,{method:'POST',body:JSON.stringify({first_view:firstView,view_count:Math.min(viewCount,(status?.quality?.registered??18)-firstView)})})).json());}
    catch(e){setError(`Построение поверхностей не подтверждено: ${e instanceof Error?e.message:'нет ответа'}. Проверяем то же задание.`);}
    finally{setSurfaceStarting(false);setRefresh(n=>n+1);}
  };
  const prepareRoute=async()=>{
    if(!job||busy)return;setSurfaceStarting(true);setPreparationNotice(null);
    try{const navigation=await prepareRouteIntent(job,scope,clip);
      setStatus(current=>current?{...current,navigation}:current);
    }catch(e){setPreparationNotice({jobId:job.id,message:preparationError(e)});if(preparationQuotaReached(e))setQuotaJob(job.id);}
    finally{setSurfaceStarting(false);setRefresh(n=>n+1);}
  };
  const surfaceLabels:Record<string,string>={starting:'Подготовка 3D-модели',preparing:'Проверка камер и оригинальных кадров',densifying:'Многовидовое восстановление глубины',meshing:'Построение треугольных поверхностей',baking:'Проекция фотографий на видимые поверхности',ready:'Текстурированная 3D-модель сохранена',review_required:'Пробная модель сохранена · проверьте поверхности визуально',failed:'Построение модели остановлено',cancelled:'Построение модели отменено'};
  return <section aria-label="Построение плотной 3D-сцены" className="space-y-4 rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/5 via-card to-sky-500/5 p-5">
    <div className="flex items-start gap-3"><Box className="mt-1 text-emerald-400" size={24}/><div><h4 className="text-lg font-semibold">Сцена из записанного прохода</h4><p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Оригинальные кадры → связанные камеры → визуальная сцена и отдельная модель поверхностей. Сохранённый результат можно вращать, изучать в каркасе и смотреть из ракурсов прохода. Обработка идёт на этом ПК, отдельно от Android.</p></div></div>
    {(attempts.length>1||!job&&attempts.length>0)&&<label className="block max-w-lg text-sm">Сохранённые попытки реконструкции<select aria-label="Сохранённая попытка реконструкции" className="mt-1 block w-full rounded-lg border border-input bg-background p-2" value={job?.id??''} disabled={busy||!folder()} onChange={e=>{void selectAttempt(e.target.value);}}>{!job&&<option value="">Новое задание</option>}{attempts.map((item,index)=><option key={item.id} value={item.id}>Попытка {index+1} · {item.id.slice(0,8)}</option>)}</select><span className="mt-1 block text-xs text-muted-foreground">Выбор открывает сохранённый результат без повторной обработки.</span></label>}
    {!status&&<div className="flex flex-wrap items-end gap-4">
      <label className="text-sm">Маска записи<select className="mt-1 block rounded-lg border border-input bg-background p-2" value={mask} onChange={e=>setMask(e.target.value)}><option value="game">HUD и персонаж в центре</option><option value="none">Без маски (чистый кадр)</option></select></label>
      <label className="text-sm">Качество обработки<select className="mt-1 block rounded-lg border border-input bg-background p-2" value={steps} onChange={e=>setSteps(Number(e.target.value))}><option value={3000}>Проба · 3 000 шагов</option><option value={5000}>Стандарт · 5 000 шагов</option><option value={10000}>Детальнее · 10 000 шагов</option><option value={30000}>Высокая детализация · 30 000 шагов</option></select></label>
      {steps===30000&&<p className="max-w-lg text-sm text-muted-foreground">Более длительная обработка исходных кадров без уменьшения FullHD. Сохраняются промежуточные результаты; ограничения памяти и проверка качества действуют. Точность камер и полнота съёмки остаются важны.</p>}
      <div className="flex flex-wrap gap-2"><Button disabled={!complete||uploading||recovering} onClick={()=>{void start(true);}}>Подготовить ориентиры</Button><Button variant="outline" disabled={!complete||uploading||recovering} onClick={()=>{void start(false);}}>Построить 3D-сцену</Button></div>
      <p className="w-full text-xs leading-5 text-muted-foreground">Подготовка ориентиров строит камеры и точки без долгого плотного рендера, затем автоматически проверяет карту. Точность пути и готовность управления проверяются отдельно.</p>
    </div>}
    {status&&<div className="flex flex-wrap items-center gap-3"><p role="status" className="flex items-center gap-2 text-sm font-medium">{busy&&<Loader2 size={16} className="animate-spin"/>}{phases[status.phase]??status.phase}{uploading&&` · ${progress}`}</p>
      {busy&&!['pending_auto_prepare','preparing','features'].includes(status.navigation?.phase??'')&&<Button variant="outline" size="sm" onClick={()=>{void cancel();}}>Отменить обработку</Button>}
      {['pending_auto_prepare','preparing','features'].includes(status.navigation?.phase??'')&&<span className="text-xs text-muted-foreground">Подготовка ориентиров выполняется отдельно; её состояние обновляется автоматически.</span>}
      {status.phase==='uploading'&&!uploading&&<Button size="sm" onClick={()=>{void start();}}>Продолжить передачу</Button>}
      {terminalReconstruction(status)&&<Button variant="outline" size="sm" onClick={()=>{sessionStorage.removeItem(storageKey);setJob(null);setStatus(null);setError(null);}}>Новое отдельное задание</Button>}
    </div>}
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {preparationNotice&&preparationNotice.jobId===job?.id&&<p role="alert" className="text-sm text-destructive">{preparationNotice.message}</p>}
    {status?.error&&<p role="alert" className="text-sm text-destructive">{reasons[status.error]??status.error} Исходное видео не изменено.</p>}
    {status?.dense_partial_available&&status.checkpoint&&<p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">Доступна проверенная промежуточная сцена: {status.checkpoint.steps} / {status.checkpoint.target_steps} итераций. Обработка не завершена успешно; это не окончательный результат.</p>}
    {status?.quality&&<p className="text-xs text-muted-foreground">Камеры {status.quality.registered}/{status.quality.selected} · покрытие {(status.quality.coverage*100).toFixed(0)}% · ошибка {status.quality.mean_reprojection_px.toFixed(2)} px</p>}
    {cameraMotionRequiresReview(status?.camera_motion)&&<p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-5 text-amber-500">Траектория камер требует проверки{status?.camera_motion?.rapid_reversals?`: ${status.camera_motion.rapid_reversals} резких смен направления за короткое время`:''}. Это может быть движение игровой камеры или ошибка восстановления. Путь не принят для управления; метры по нему не вычисляются.</p>}
    {job&&status?.geometry_available&&<div className="space-y-3 rounded-xl border border-sky-500/25 bg-sky-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h5 className="font-medium">3D-модель поверхностей</h5><p className="mt-1 text-xs leading-5 text-muted-foreground">Треугольная сетка с фотографическими текстурами. Невидимые участки остаются пустыми; исходная сцена сохраняется отдельно.</p></div>
      <Button variant="outline" disabled={busy||!status.dense_available||!status.surface_supported||!terminalReconstruction(status)} onClick={()=>{void startSurface();}}>{models.length?'Построить другой фрагмент':'Построить поверхности'}</Button></div>
      <div className="flex flex-wrap items-end gap-4 text-xs"><label>Начальный ракурс<input disabled={busy} aria-label="Начальный ракурс фрагмента" className="mt-1 block w-28 rounded-md border bg-background p-2" type="number" min={1} max={Math.max(1,(status.quality?.registered??18)-2)} value={firstView+1} onChange={e=>setFirstView(Math.max(0,Math.min((status.quality?.registered??18)-3,Number(e.target.value)-1)))}/></label><label>Длина фрагмента<select disabled={busy} className="ml-2 rounded-md border bg-background p-2" value={viewCount} onChange={e=>setViewCount(Number(e.target.value))}><option value={12}>12 ракурсов</option><option value={18}>18 ракурсов</option><option value={24}>24 ракурса</option></select></label><p className="max-w-xl text-muted-foreground">Каждый участок сохраняется отдельно в этом маршруте. Повторно восстанавливать все камеры не требуется; модели не сшиваются автоматически.</p></div>
      {models.length>0&&<label className="block text-sm">Сохранённые участки<select aria-label="Сохранённый фрагмент маршрута" className="mt-2 block w-full rounded-lg border bg-background p-2" value={selectedModel?.id??'legacy'} onChange={e=>setSelectedFragment(e.target.value)}>{models.map((item,index)=><option key={item.id??'legacy'} value={item.id??'legacy'} disabled={!item.available}>Участок {index+1}{item.fragment?` · ракурсы ${item.fragment.first_view+1}–${item.fragment.first_view+item.fragment.view_count}`:''} · {surfaceLabels[item.phase]??item.phase}</option>)}</select></label>}
      {workingSurface&&<p role="status" className="text-sm">{surfaceLabels[workingSurface.phase]??workingSurface.phase}{workingSurface.total_views?` · ${workingSurface.views}/${workingSurface.total_views} ракурсов`:''}</p>}
      {selectedModel?.phase==='review_required'&&<p className="text-xs leading-5 text-amber-500">Осмотрите модель из нескольких ракурсов: ложные перемычки и разрывы возможны. Готовность файла не означает точную геометрию или допуск навигации.</p>}
      {selectedModel?.visual_review?.state==='issues_found'&&<p role="status" className="rounded-lg border border-amber-500/30 p-3 text-xs leading-5 text-amber-500">В проверенных ракурсах этого участка найдены дефекты: {selectedModel.visual_review.issues.map(issue=>({holes:'пропуски поверхностей',occluding_surfaces:'ложные перекрытия',stretched_triangles:'растянутые треугольники',pose_inconsistency:'сомнительное положение камер'})[issue]??issue).join(', ')}. Он доступен для диагностики и не считается качественной картой.</p>}
      {models.filter(item=>item.error).map(item=><p key={item.id??'legacy'} role="alert" className="text-sm text-destructive">{reasons[item.error!]??item.error}. Исходные материалы и предыдущая сцена сохранены.</p>)}
      {selectedModel?.result&&<p className="text-xs text-muted-foreground">{selectedModel.result.triangles.toLocaleString('ru')} треугольников · {selectedModel.result.textures} фотографий · {(selectedModel.result.bytes/1048576).toFixed(1)} МБ · исключено без видимого покрытия: {selectedModel.result.unknown_faces.toLocaleString('ru')} граней</p>}
      {!status.surface_supported&&!status.surface&&<p className="text-xs text-muted-foreground">Локальный инструмент OpenMVS CPU ещё не подготовлен.</p>}
    </div>}
    {visible&&job&&status?.dense_available&&<ReferenceComparison job={job} appearance={status.appearance}/>}
    {job&&status?.geometry_available&&<div className="space-y-3 rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h5 className="font-medium">Карта ориентиров для живой проверки</h5><p className="mt-1 text-xs leading-5 text-muted-foreground">Сохранённые камеры и реальные 3D-опоры → определение положения по свежему кадру. Воспроизведение нажатий не используется.</p></div><Button variant="outline" disabled={busy||!(status.dense_available||status.sparse_available)||cameraMotionRequiresReview(status.camera_motion)||status.navigation?.error==='route_camera_motion_requires_review'||status.navigation?.error==='route_preparation_attempt_quota'||status.navigation?.error==='route_map_has_unobserved_sections'||quotaJob===job.id||status.navigation?.phase==='ready'} onClick={()=>{void prepareRoute();}}>{status.navigation?.phase==='ready'?'Карта подготовлена':'Подготовить маршрут'}</Button></div><p role="status" className="text-xs">{status.navigation?.phase==='ready'?`Готово для ручной проверки · ${status.navigation.summary?.cameras??'—'} камер · ${status.navigation.summary?.landmarks??'—'} ориентиров`:!(status.dense_available||status.sparse_available)?'Камеры или обработка сцены не прошли проверку; ориентиры пока не подготовить.':cameraMotionRequiresReview(status.camera_motion)?'Траектория камер требует проверки; повторная подготовка не исправит её.':navigationPhaseLabel(status.navigation?.phase)}{status.navigation?.error?` · ${navigationErrorLabel(status.navigation.error)}`:''}</p>{routeCoverageLabel(status.navigation?.summary)&&<p className="text-xs text-muted-foreground">{routeCoverageLabel(status.navigation?.summary)}</p>}<p className="text-xs leading-5 text-muted-foreground">После подготовки откройте режим «Направление» наверху страницы. Это ещё не допуск автономной поездки: поверхность дороги, препятствия и моторная модель проверяются отдельно.</p></div>}
    {alternativeCameraCount!==null&&<p className="rounded-lg border border-cyan-500/25 bg-cyan-500/5 p-3 text-xs leading-5">Схема на {alternativeCameraCount} камер открыта выше. Ниже — 3D-представление основной попытки ({status?.quality?.registered??'—'} камер); эти результаты рассчитаны отдельно.</p>}
    {visible&&job&&status?.geometry_available&&<Scene job={job} status={{...status,surface:selectedModel??status.surface}} sourceManifestSha={sourceManifestSha} selectedTicks={selectedTicks} onSeekCamera={onSeekCamera} validTicks={validTicks} sourcePreview={sourcePreview} showGeometryMap={alternativeCameraCount===null}/>}
    <p className="text-xs text-muted-foreground">Ссылка на результат сохранена рядом с записью в библиотеке этого браузера и аккаунта. Выберите этот проход снова, чтобы открыть готовую сцену. Сохранённая сцена остаётся на локальном ПК.</p>
    <p className="text-xs leading-5 text-muted-foreground">Маска применяется до поиска признаков; она не распознаёт все движущиеся машины и игроков. Плотная сцена — визуальная реконструкция, а не готовая карта коллизий. Масштаб в метрах требует отдельного известного расстояния. При нехватке связных ракурсов обработка остановится с объяснением.</p>
  </section>;
}
