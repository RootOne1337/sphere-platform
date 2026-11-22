import type {sceneCameraCoverage} from './sceneGeometrySelection';

type Coverage=NonNullable<ReturnType<typeof sceneCameraCoverage>>;
const seconds=(value:number)=>`${value.toFixed(3)} с`;
const interval=(first:number,last:number)=>`${first.toFixed(3)}–${last.toFixed(3)} с`;

/** Source time and measured references only; never a per-frame pose or accuracy claim. */
export function CameraCoverageNotice({coverage}:{coverage:Coverage}) {
  const startMissing=coverage.knownSource&&coverage.uncoveredStart>0,endMissing=coverage.knownSource&&coverage.uncoveredEnd>0;
  const missing=[startMissing?interval(coverage.sourceStart,coverage.first):null,endMissing?interval(coverage.last,coverage.sourceEnd):null].filter(Boolean);
  return <section aria-label="Время исходного видео и восстановленных камер" className="min-h-28 space-y-2 rounded-lg border border-sky-500/25 bg-sky-500/5 p-3 text-xs leading-5">
    <div className="flex flex-wrap justify-between gap-x-6 gap-y-1 tabular-nums">
      <p className="font-medium">{coverage.knownSource?`Исходное видео целиком: ${interval(coverage.sourceStart,coverage.sourceEnd)} · кадров: ${coverage.sourceFrames}`:'Полный временной интервал исходного видео не подтверждён.'}</p>
      <p>Камеры в интервале {interval(coverage.first,coverage.last)} · ракурсов: {coverage.views}</p>
    </div>
    {coverage.knownSource&&<div className="relative h-2 overflow-hidden rounded-full bg-muted" aria-label="Временные группы восстановленных камер">
      {coverage.cameraIntervals.map((group,index)=><span key={index} className="absolute inset-y-0 min-w-px rounded-full bg-cyan-400" style={{left:`${coverage.sourceEnd>coverage.sourceStart?(group.first-coverage.sourceStart)/(coverage.sourceEnd-coverage.sourceStart)*100:0}%`,width:`${coverage.sourceEnd>coverage.sourceStart?(group.last-group.first)/(coverage.sourceEnd-coverage.sourceStart)*100:0}%`}}/>)}
    </div>}
    <p className={missing.length?'text-amber-700 dark:text-amber-300':'text-muted-foreground'}>{missing.length?
      `${startMissing&&endMissing?'Начало и конец видео сохранены':startMissing?'Начало видео сохранено':'Конец видео сохранён'}; положения камер на этих участках ещё не восстановлены: ${missing.join('; ')}.`:
      'Показаны только восстановленные камеры. Их временной диапазон не означает, что положение вычислено для каждого кадра.'}</p>
    {coverage.gaps.length>0&&<details><summary className="cursor-pointer text-muted-foreground">Внутренние интервалы без соседних камер: {coverage.gaps.length} · {seconds(coverage.gapSeconds)}</summary><p className="mt-1 tabular-nums text-muted-foreground">{coverage.gaps.map(gap=>interval(gap.first,gap.last)).join('; ')}</p></details>}
    <p className="text-muted-foreground">{coverage.knownSource&&'Ползунок видео включает всю запись. '}Полоса показывает группы соседних камер с шагом до 1 с; это не оценка точности геометрии. Недостающие позы не достраиваются.</p>
  </section>;
}
