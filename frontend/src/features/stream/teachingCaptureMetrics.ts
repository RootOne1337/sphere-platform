export function teachingCaptureMetrics(rows:{relative_ticks_90k:number;bytes:number}[]) {
  const seconds=rows.length?(rows[rows.length-1].relative_ticks_90k-rows[0].relative_ticks_90k)/90000:0;
  const intervals=rows.slice(1).map((row,i)=>(row.relative_ticks_90k-rows[i].relative_ticks_90k)/90);
  if(rows.length>36000||!Number.isFinite(seconds)||seconds<0||seconds>86400||intervals.some(n=>!Number.isFinite(n)||n<=0))return null;
  const sorted=[...intervals].sort((a,b)=>a-b),fps=seconds>0?(rows.length-1)/seconds:null;
  const percentile=(p:number)=>sorted.length?sorted[Math.min(sorted.length-1,Math.floor((sorted.length-1)*p))]:null;
  const bytes=rows.reduce((sum,row)=>sum+row.bytes,0);
  const bucket=Math.max(1,Math.ceil(intervals.length/100)),chart:number[]=[];
  for(let i=0;i<intervals.length;i+=bucket)chart.push(Math.max(...intervals.slice(i,i+bucket)));
  return {frames:rows.length,seconds,fps,bitrateBps:seconds>0?bytes*8/seconds:null,maxGapMs:sorted.at(-1)??null,
    p50GapMs:percentile(.5),p95GapMs:percentile(.95),gaps200:intervals.filter(n=>n>200).length,gaps1000:intervals.filter(n=>n>1000).length,
    cadence30Confirmed:seconds>=3&&fps!==null&&fps>=29.5&&!intervals.some(n=>n>200),
    chart};
}
