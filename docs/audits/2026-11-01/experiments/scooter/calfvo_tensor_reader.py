"""Read-only, bounded, experimental ZIP_STORED tensor reader; never writes source."""
import hashlib,struct,zipfile,os
import torch
from torch._subclasses.fake_tensor import FakeTensorMode

ALLOWED={torch.float16,torch.float32,torch.float64,torch.bfloat16,torch.int8,torch.uint8,torch.int16,torch.int32,torch.int64,torch.bool}
MAX_READ=64*1024*1024
def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def fake_state(path):
    with FakeTensorMode(): obj=torch.load(path,map_location='cpu',weights_only=True,mmap=False)
    return obj.get('model_state_dict',obj)
def zip_entries(path):
    entries=[]
    with zipfile.ZipFile(path) as z,open(path,'rb') as f:
        for x in z.infolist():
            f.seek(x.header_offset); h=f.read(30)
            if len(h)!=30 or h[:4]!=b'PK\x03\x04':raise ValueError('invalid_zip_local_header')
            n,e=struct.unpack_from('<HH',h,26);start=x.header_offset+30+n+e
            entries.append((start,start+x.file_size,x.compress_type,x.filename))
    return entries
def descriptor(t,entries):
    if t.dtype not in ALLOWED:raise ValueError('unsupported_dtype')
    off=getattr(t.untyped_storage(),'_checkpoint_offset',None)
    if not isinstance(off,int):raise ValueError('checkpoint_offset_unavailable')
    shape=tuple(t.shape);stride=tuple(t.stride());elem=t.element_size();base=t.storage_offset()
    if base<0 or any(s<0 for s in stride):raise ValueError('unsupported_layout')
    count=0 if t.numel()==0 else 1+sum((n-1)*s for n,s in zip(shape,stride))
    start=off+base*elem;length=count*elem
    if length>MAX_READ:raise ValueError('tensor_span_exceeds_64MiB')
    matches=[x for x in entries if x[0]<=start and start+length<=x[1]]
    if len(matches)!=1 or matches[0][2]!=zipfile.ZIP_STORED:raise ValueError('storage_range_invalid_or_compressed')
    return {'offset':start,'bytes':length,'shape':shape,'stride':stride,'dtype':t.dtype,'entry':matches[0][3]}
def read_tensor(f,d):
    if not d['bytes']:return torch.empty_strided(d['shape'],d['stride'],dtype=d['dtype'])
    buf=bytearray(d['bytes']);f.seek(d['offset']);n=f.readinto(buf)
    if n!=len(buf):raise EOFError('short_tensor_read')
    return torch.frombuffer(buf,dtype=d['dtype']).as_strided(d['shape'],d['stride'])
