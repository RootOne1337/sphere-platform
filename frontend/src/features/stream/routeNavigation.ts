/** Read-only same-query-frame preview. No native input/model permit. */
export type NavigationReply = {id:string;sequence:number;captureEpoch:string;jpegSha256:string;computeMs:number;method:string;
  physicalActions:0;executionQualified:false;groundRoute:false;pose:{state:'unknown'|'confirming'|'localized';reason:string;
    inliers:number;segment:number|null;progress_units:number|null;polyline_px:[number,number][]}};
export function navigationReply(value:unknown,id:string,epoch:string,sequence:number,jpegSha256:string):NavigationReply|null {
  const v=value as NavigationReply,p=v?.pose;
  if(!v||v.id!==id||v.captureEpoch!==epoch||v.sequence!==sequence||v.physicalActions!==0||v.executionQualified!==false||v.groundRoute!==false
    ||!Number.isFinite(v.computeMs)||v.computeMs<0||v.computeMs>10000||!/^[0-9a-f]{64}$/.test(v.jpegSha256)||v.jpegSha256!==jpegSha256
    ||!p||!['unknown','confirming','localized'].includes(p.state)||typeof p.reason!=='string'||p.reason.length>200
    ||!Number.isInteger(p.inliers)||p.inliers<0||p.inliers>4096||!Array.isArray(p.polyline_px)||p.polyline_px.length>16
    ||p.polyline_px.some(row=>!Array.isArray(row)||row.length!==2||row.some((n,i)=>!Number.isFinite(n)||n<0||n>=[960,540][i]))
    ||p.state!=='localized'&&p.polyline_px.length>0)return null;
  return v;
}
export function freshNavigationFrame(capturedAt:number,now:number):boolean {
  return Number.isFinite(capturedAt)&&Number.isFinite(now)&&now>=capturedAt&&now-capturedAt<=250;
}
export function paintNavigation(context:CanvasRenderingContext2D,source:HTMLCanvasElement,result:NavigationReply) {
  context.clearRect(0,0,960,540);context.drawImage(source,0,0);
  const line=result.pose.polyline_px;
  if(result.pose.state!=='localized'||line.length<2)return;
  context.save();context.lineJoin='round';context.lineCap='round';
  const path=()=>{context.beginPath();line.forEach(([x,y],i)=>i?context.lineTo(x,y):context.moveTo(x,y));};
  path();context.strokeStyle='rgba(6,15,24,.8)';context.lineWidth=6;context.stroke();
  path();context.strokeStyle='#61ead8';context.lineWidth=2.5;context.stroke();
  // Small attached chevrons explain direction without replacing the scene by
  // a thick synthetic road or inventing an origin on the ground.
  for(let i=1;i<line.length;i++){
    const [x,y]=line[i],[px,py]=line[i-1],angle=Math.atan2(y-py,x-px);
    if(Math.hypot(x-px,y-py)<12)continue;
    context.beginPath();context.moveTo(x-Math.cos(angle-.55)*10,y-Math.sin(angle-.55)*10);
    context.lineTo(x,y);context.lineTo(x-Math.cos(angle+.55)*10,y-Math.sin(angle+.55)*10);
    context.stroke();
  }
  const [x,y]=line[line.length-1];context.beginPath();context.arc(x,y,4,0,Math.PI*2);context.fillStyle='#ecfff9';context.fill();
  context.restore();
}
