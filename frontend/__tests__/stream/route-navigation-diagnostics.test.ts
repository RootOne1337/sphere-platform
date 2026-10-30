import {RouteNavigationDiagnostics} from '@/src/features/stream/routeNavigationDiagnostics';
import {navigationReply} from '@/src/features/stream/routeNavigation';

const response=()=>({id:'session',captureEpoch:'epoch',sequence:4,jpegSha256:'a'.repeat(64),computeMs:25,
  method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
  pose:{state:'localized',reason:'relative_camera_pose_not_clearance_or_arrival',inliers:50,segment:4,progress_units:1,
    polyline_px:[[400,350],[450,300]],unused:'secret-payload'}});
const valid=()=>navigationReply(response(),'session','epoch',4,'a'.repeat(64))!;

test('export includes bound observations and lateness without image, identifiers or input',()=>{
  const log=new RouteNavigationDiagnostics('job','clip',1000);
  log.add(valid(),1100,1351);
  const result=log.export();
  expect(result).toMatchObject({jobId:'job',clipId:'clip',physicalActions:0,executionQualified:false,groundRoute:false,
    fullAndroidLatencyKnown:false,framesIncluded:false,inputsIncluded:false,samplesOmitted:0,
    samples:[{elapsedMs:100,state:'localized',segment:4,frameToReplyMs:251,late:true}]});
  expect(JSON.stringify(result)).not.toMatch(/secret-payload|jpegSha256|captureEpoch|session|polyline_px/);
  result.samples[0].segment=77;
  expect(log.export().samples[0].segment).toBe(4);
});

test('samples are bounded and invalid clock values do not become evidence',()=>{
  const log=new RouteNavigationDiagnostics('job',null,1000);
  log.add(valid(),999,1001);log.add(valid(),1100,1099);log.add(valid(),NaN,1100);
  expect(log.size).toBe(0);
  for(let n=0;n<1203;n++)log.add(valid(),1100+n,1200+n);
  expect(log.size).toBe(1200);expect(log.export().samplesOmitted).toBe(3);
});

test('malformed segment, progress, method or reason never enters diagnostics',()=>{
  const base=response();
  for(const value of [
    {...base,method:'private / information'},
    {...base,pose:{...base.pose,reason:'bad / reason'}},
    {...base,pose:{...base.pose,segment:-1}},
    {...base,pose:{...base.pose,segment:undefined}},
    {...base,pose:{...base.pose,progress_units:Infinity}},
  ])expect(navigationReply(value,'session','epoch',4,'a'.repeat(64))).toBeNull();
});
