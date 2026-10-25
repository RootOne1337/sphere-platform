export type RecordedCamera={image:string;ticks_90k:number;center:number[]};

/** Coverage of recorded timestamps, never a claim about reconstructed surfaces or metres. */
export function routeCoverage(cameras:RecordedCamera[],images:string[]) {
  const included=new Set(images),selected=cameras.filter(camera=>included.has(camera.image));
  if(!cameras.length||!selected.length)return null;
  const first=selected[0].ticks_90k/90000,last=selected.at(-1)!.ticks_90k/90000;
  const start=cameras[0].ticks_90k/90000,end=cameras.at(-1)!.ticks_90k/90000;
  let covered=0;
  for(let i=1;i<cameras.length;i++)if(included.has(cameras[i-1].image)&&included.has(cameras[i].image))covered+=(cameras[i].ticks_90k-cameras[i-1].ticks_90k)/90000;
  return {first,last,sourceStart:start,sourceEnd:end,views:selected.length,totalViews:cameras.length,coveredSeconds:covered,fraction:end>start?covered/(end-start):0};
}
