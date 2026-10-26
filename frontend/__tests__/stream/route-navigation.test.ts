import {freshNavigationFrame,navigationReply,paintNavigation} from '@/src/features/stream/routeNavigation';
import {teachingCaptureMetrics} from '@/src/features/stream/teachingCaptureMetrics';
const reply=()=>({id:'id',captureEpoch:'epoch',sequence:4,jpegSha256:'a'.repeat(64),computeMs:10,method:'map_anchored_flow',physicalActions:0,executionQualified:false,groundRoute:false,
  pose:{state:'localized',reason:'diagnostic',inliers:50,segment:4,progress_units:1.,polyline_px:[[400,350],[450,300],[500,250]]}});
test('a result must match the exact query image, session, epoch and sequence without input permission',()=>{
  expect(navigationReply(reply(),'id','epoch',4,'a'.repeat(64))).not.toBeNull();
  for(const change of [{id:'other'},{captureEpoch:'old'},{sequence:3},{jpegSha256:'b'.repeat(64)},{physicalActions:1},{executionQualified:true}]){
    expect(navigationReply({...reply(),...change},'id','epoch',4,'a'.repeat(64))).toBeNull();
  }
  expect(navigationReply({...reply(),pose:{...reply().pose,state:'unknown'}},'id','epoch',4,'a'.repeat(64))).toBeNull();
  expect(freshNavigationFrame(1000,1250)).toBe(true);expect(freshNavigationFrame(1000,1251)).toBe(false);expect(freshNavigationFrame(1001,1000)).toBe(false);
});
test('unknown poses preserve query pixels without a fabricated connected path',()=>{
  const context={clearRect:jest.fn(),drawImage:jest.fn(),save:jest.fn(),beginPath:jest.fn(),stroke:jest.fn()};
  const value={...reply(),pose:{...reply().pose,state:'unknown' as const,polyline_px:[]}};
  paintNavigation(context as never,{} as never,value as never);
  expect(context.drawImage).toHaveBeenCalledTimes(1);expect(context.stroke).not.toHaveBeenCalled();
});
test('recording cadence is derived from real frame intervals, not a 30 or 60 FPS configuration',()=>{
  const rows=(delta:number)=>Array.from({length:101},(_,i)=>({relative_ticks_90k:i*delta,bytes:1000}));
  expect(teachingCaptureMetrics(rows(9000))).toMatchObject({fps:10,cadence30Confirmed:false,maxGapMs:100});
  expect(teachingCaptureMetrics(rows(3000))).toMatchObject({fps:30,cadence30Confirmed:true});
  const bad=rows(3000);bad[80].relative_ticks_90k=bad[79].relative_ticks_90k;
  expect(teachingCaptureMetrics(bad)).toBeNull();
});
