import os,sys,json,time,hashlib,socket,traceback,math,ctypes
from pathlib import Path
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
def deny(*a,**kw):raise RuntimeError('network disabled in smoke')
socket.socket.connect=deny;socket.create_connection=deny
base=Path('.local-pilot/reconstruction-tools'); src=base/'calfvo-64497981704a'; deps=base/'calfvo-64497981704a-composite'
sys.path[0:0]=[str(x.resolve()) for x in (src,deps,deps/'croco',deps/'dust3r',Path('.local-pilot/calfvo-python-target'),Path('.local-pilot/route-fusion-runtime'))]
output=Path('.local-pilot/scooter-calfvo-full-20261101'); research=Path('.local-pilot/scooter-yaw-20261101'); start=time.monotonic()
class Memory(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total_phys',ctypes.c_ulonglong),('free_phys',ctypes.c_ulonglong),('total_page',ctypes.c_ulonglong),('free_page',ctypes.c_ulonglong),('total_virtual',ctypes.c_ulonglong),('free_virtual',ctypes.c_ulonglong),('extended',ctypes.c_ulonglong)]
class ProcessMemory(ctypes.Structure):
    _fields_=[('cb',ctypes.c_ulong),('page_faults',ctypes.c_ulong),('peak_working_set',ctypes.c_size_t),('working_set',ctypes.c_size_t),('quota_peak_paged',ctypes.c_size_t),('quota_paged',ctypes.c_size_t),('quota_peak_nonpaged',ctypes.c_size_t),('quota_nonpaged',ctypes.c_size_t),('pagefile_usage',ctypes.c_size_t),('peak_pagefile',ctypes.c_size_t),('private_usage',ctypes.c_size_t)]
gpu_ready=False
def phase(name,**extra):
    m=Memory();m.length=ctypes.sizeof(m);ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    pm=ProcessMemory();pm.cb=ctypes.sizeof(pm)
    ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(ProcessMemory),ctypes.c_ulong]
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(pm),pm.cb):raise OSError('process_memory_query_failed')
    record={'phase':name,'elapsed_s':round(time.monotonic()-start,2),'free_physical_bytes':m.free_phys,'free_commit_bytes':m.free_page,'child_private_bytes':pm.private_usage,'child_working_set_bytes':pm.working_set,**extra}
    if gpu_ready:record.update(gpu_allocated_bytes=torch.cuda.memory_allocated(),gpu_reserved_bytes=torch.cuda.memory_reserved())
    with (output/'phases.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(record)+'\n')
    if name!='failed' and (m.free_phys<4.5*2**30 or m.free_page<4.5*2**30):raise RuntimeError('host_reserve_below_4.5GiB')
phase('started')
try:
    import torch,cv2,numpy as np,importlib.util
    from PIL import Image
    import src.model
    from transformers import Dinov2Config,Dinov2Model
    from src.utils.training_utils import get_transforms,AspectPreservingCropAndResize,recover_trajectory
    from src.utils.data_utils import create_overlapping_windows
    from torchvision import transforms
    torch.set_num_threads(2);cv2.setNumThreads(2)
    strict=json.loads((research/'strict-checkpoint-probe.json').read_text(encoding='utf-8-sig'))
    if isinstance(strict,list):strict=strict[0]
    result=json.loads(strict['stdout'].strip().splitlines()[-1])
    if strict['guard'] or result['status']!='strict_state_passed' or any(result[k] for k in ('missing','unexpected','shape_mismatch','dtype_mismatch')):raise RuntimeError('strict_check_not_exact')
    receipt=json.loads((base/'calfvo-models/progress.json').read_text())
    if receipt['status']!='verified' or receipt['sha256']!='ca3531dbbdeec1e1ff3f5300ab236d3d529b413eb7fe89769a174def07f37ecd':raise RuntimeError('checkpoint_receipt_invalid')
    checkpoint=base/'calfvo-models/calfvo_dinov2.pth'
    if checkpoint.stat().st_size!=2079011438:raise RuntimeError('checkpoint_size_changed')
    probe=json.loads((research/'stream-probe-result.json').read_text())
    if probe['status']!='passed' or probe['checkpoint_tensors']!=686 or not all(probe['fixture_checks'].values()):raise RuntimeError('stream_preflight_failed')
    spec=importlib.util.spec_from_file_location('loader',research/'calfvo-stream-loader.py');loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
    phase('before_checkpoint_hash')
    if loader.digest(checkpoint)!=receipt['sha256']:raise RuntimeError('checkpoint_pre_hash_mismatch')
    phase('after_checkpoint_hash')
    if not torch.cuda.is_available():raise RuntimeError('rocm_gpu_unavailable')
    free,total=torch.cuda.mem_get_info(); cap=min(int(4*2**30),free-2*2**30,int(total*.35))
    if free<8*2**30 or cap<=0:raise RuntimeError('gpu_free_below_8GiB_or_reserve_unavailable')
    torch.cuda.set_per_process_memory_fraction(cap/total)
    gpu_ready=True
    phase('gpu_admitted',gpu_name=torch.cuda.get_device_name(0),free_bytes=free,total_bytes=total,allocator_cap_bytes=cap)
    job=Path('.local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e'); video=job/'input/video.h264'
    sha=hashlib.sha256(video.read_bytes()).hexdigest()
    if sha!='0feaeae732c30d2f25ff1359f276f78f53ed029538243ac1b42ae1537192df1e':raise RuntimeError('video_hash_mismatch')
    records=[json.loads(x) for x in (job/'input/frames.jsonl').read_text().splitlines()]
    if len(records)!=901 or any(r['index']!=i for i,r in enumerate(records)):raise RuntimeError('frame_index_mismatch')
    capvid=cv2.VideoCapture(str(video));checks={}; cache=np.empty((901,224,224,3),dtype=np.uint8)
    crop=AspectPreservingCropAndResize([224,224],train=False)
    norm=transforms.Compose([transforms.ToTensor(),transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
    transform=get_transforms([224,224],train=False,norm_mean=[.485,.456,.406],norm_std=[.229,.224,.225])
    binding=json.loads((research/'binding.json').read_text());check_indices={x['index'] for x in binding['sampled_pixels']}
    for i in range(901):
        ok,frame=capvid.read()
        if not ok:raise RuntimeError('video_decode_failed')
        if i in check_indices:
            ref=cv2.imread(str(Path('.local-pilot/zaezd888-diagnosis-20261031/dense-tracks/images')/f'{i:08d}.png'))
            checks[str(i)]=bool(np.array_equal(frame,ref))
            if not checks[str(i)]:raise RuntimeError('prepared_image_binding_mismatch')
        image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB),mode='RGB')
        resized=crop(image);cache[i]=np.asarray(resized)
        if i<2 and not torch.equal(transform(image),norm(Image.fromarray(cache[i],mode='RGB'))):raise RuntimeError('preprocessing_mismatch')
    if capvid.read()[0]:raise RuntimeError('video_contains_extra_frames')
    capvid.release()
    phase('frames_prepared',frames=901,cache_bytes=int(cache.nbytes),png_bindings=len(checks),preprocessing_sample_exact=True)
    cfg=Dinov2Config.from_dict(json.loads((research/'dinov2-large-config.json').read_text()))
    conf=dict(backbone='dinov2_large',embed_dim=1024,patch_size=16,img_size=[224,224],depth=12,num_views=8)
    def local_backbone(*a,**kw):return src.model.backbone.DinoV2Backbone(Dinov2Model(cfg))
    src.model.get_backbone=local_backbone
    orig=torch.linspace
    def cpu_linspace(*a,**kw):
        if a==(0,0.1,12) and 'device' not in kw:kw['device']='cpu'
        return orig(*a,**kw)
    torch.linspace=cpu_linspace
    phase('before_meta_construction')
    try:
        with torch.device('meta'): model=src.model.get_model(conf)
    finally:torch.linspace=orig
    phase('after_meta_construction')
    phase('before_checkpoint_fake_metadata')
    fake=loader.fake_state(checkpoint);entries=loader.zip_entries(checkpoint)
    weights={k.replace('_orig_mod.','',1):v for k,v in fake.items()}
    desc={k:loader.descriptor(v,entries) for k,v in weights.items()}
    phase('after_checkpoint_fake_metadata',tensors=len(desc),max_span_bytes=max(d['bytes'] for d in desc.values()))
    meta=model.state_dict()
    if set(meta)!=set(weights) or any(meta[k].dtype!=weights[k].dtype or meta[k].shape!=weights[k].shape for k in meta):raise RuntimeError('checkpoint_state_mismatch')
    model.half();model.head.float()
    phase('before_gpu_to_empty')
    model=model.to_empty(device='cuda').eval()
    phase('after_gpu_to_empty')
    target=model.state_dict(keep_vars=True)
    with checkpoint.open('rb') as source,torch.no_grad():
        for j,k in enumerate(target):
            data=loader.read_tensor(source,desc[k])
            target[k].copy_(data,non_blocking=False)
            del data
            if (j+1)%100==0:phase('copy_progress',tensors_copied=j+1)
    torch.cuda.synchronize();phase('after_tensor_copy',tensors_copied=len(target))
    del target,meta,weights,fake,desc
    # Upstream recovery right-multiplies camera-relative transforms. Test both
    # overlapping edges and rotation-dependent translation before real outputs.
    tw=np.array([np.arange(8),np.arange(4,12)])
    fake_poses=np.repeat(np.eye(4)[None],14,axis=0)
    for j in range(14):fake_poses[j,0,3]=1
    for j in range(2):
        if j==0: fake_poses[j,:3,:3]=np.array([[0.,-1,0],[1,0,0],[0,0,1]])
    fake_traj=recover_trajectory(fake_poses,tw,np.ones((14,2)))
    if len(fake_traj)!=12 or not np.allclose(fake_traj[-1,:3,3],[1,10,0],atol=1e-4):raise RuntimeError('synthetic_aggregation_fixture_failed')
    phase('aggregation_fixture_passed')
    windows=create_overlapping_windows(np.arange(901),window_size=8,overlap=4).tolist()
    if windows[-1][-1]!=899:raise RuntimeError('unexpected_upstream_window_tail')
    windows.append(list(range(893,901)))
    seen=[]; allposes=[]; allconf=[]; times=[]; partial=False
    with (output/'windows.jsonl').open('x',encoding='utf8',buffering=1) as file:
        for j,idx in enumerate(windows):
            if time.monotonic()-start>220:
                partial=True;break
            input_batch=torch.stack([norm(Image.fromarray(cache[i],mode='RGB')) for i in idx]).permute(1,0,2,3).unsqueeze(0).to(device='cuda',dtype=torch.float16)
            t0=time.monotonic()
            with torch.no_grad(): pred=model(input_batch)
            torch.cuda.synchronize(); dt=time.monotonic()-t0
            poses=pred['relative_poses'].detach().cpu();logvar=pred['confidences'].detach().cpu()
            if not torch.isfinite(poses).all() or not torch.isfinite(logvar).all():raise RuntimeError('nonfinite_model_output')
            poses=poses.clone();poses[:,:,:3,3]=poses[:,:,:3,3]*torch.tensor([.2,.1,.2])+torch.tensor([0.,0.,.01])
            confs=torch.exp(-logvar)
            if not torch.isfinite(confs).all():raise RuntimeError('nonfinite_confidence')
            row={'indices':idx,'ticks_90k':[records[i]['relative_ticks_90k'] for i in idx],'relative_poses_denormalized':poses[0].tolist(),'confidence_exp_negative_log_variance':confs[0].tolist(),'forward_s':dt}
            file.write(json.dumps(row,allow_nan=False)+'\n');file.flush()
            seen.append(idx);allposes.append(poses[0].numpy());allconf.append(confs[0].numpy());times.append(dt)
            if j==1:
                estimate=(len(windows)-2)*times[-1];phase('two_window_warm_estimate',first_forward_s=times[0],second_forward_s=times[1],remaining_windows=len(windows)-2,estimate_s=estimate,remaining_wall_s=240-(time.monotonic()-start))
            if (j+1)%20==0:phase('window_progress',windows=j+1,last_frame=idx[-1])
    if not seen:raise RuntimeError('no_completed_windows')
    frame_ids=np.array(seen,dtype=int); relative=np.concatenate(allposes); confidence=np.concatenate(allconf)
    edges=[];found=set()
    for ids in seen:
        for a,b in zip(ids[:-1],ids[1:]):
            if (a,b) not in found:found.add((a,b));edges.append((a,b))
    if edges!=[(i,i+1) for i in range(edges[-1][1])]:raise RuntimeError('noncontiguous_edge_order')
    trajectory=recover_trajectory(relative,frame_ids,confidence)
    if len(trajectory)!=len(edges)+1 or not np.isfinite(trajectory).all():raise RuntimeError('aggregation_output_invalid')
    np.savez_compressed(output/'candidate.npz',frame_indices=np.arange(len(trajectory)),ticks_90k=np.array([records[i]['relative_ticks_90k'] for i in range(len(trajectory))]),trajectory_c2w=trajectory,window_frame_ids=frame_ids,relative_poses=relative,confidence=confidence)
    phase('before_final_hashes')
    final_sha=loader.digest(checkpoint); video_after=loader.digest(video)
    if final_sha!=receipt['sha256'] or video_after!=sha:raise RuntimeError('source_post_hash_mismatch')
    result={'status':'partial' if partial or len(seen)!=len(windows) else 'complete','total_input_frames':901,'total_planned_windows':len(windows),'completed_windows':len(seen),'last_processed_frame':edges[-1][1],'unprocessed_frame_indices':list(range(edges[-1][1]+1,901)),'upstream_window_overlap':4,'tail_window':list(range(893,901)),'tail_is_explicit_extension':True,'upstream_recover_trajectory':True,'synthetic_aggregation_fixture':'passed','hash_checkpoint_before_after':final_sha,'hash_video_before_after':video_after,'png_pixel_binding_count':len(checks),'forward_first_two_s':times[:2],'forward_mean_after_first_two_s':float(np.mean(times[2:])) if len(times)>2 else None,'elapsed_s':time.monotonic()-start,'max_gpu_allocated_bytes':torch.cuda.max_memory_allocated(),'max_gpu_reserved_bytes':torch.cuda.max_memory_reserved(),'limits':'Experimental camera trajectory in learned model units, no metric validation, no route or execution qualification; FP16 not proven equivalent FP32; confidence not calibrated.'}
    (output/'result.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf8');phase('completed',status=result['status']);print(json.dumps(result),flush=True)
except Exception as e:
    status={'status':'failed','exception_type':type(e).__name__,'exception_message':str(e)[:1500],'traceback':[{'file':os.path.basename(x.filename),'line':x.lineno,'function':x.name} for x in traceback.extract_tb(e.__traceback__)]}
    phase('failed',**status);print(json.dumps(status),flush=True);raise SystemExit(1)
