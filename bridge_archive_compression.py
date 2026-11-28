
"""Lossless archive compression with verified restoration."""
import argparse,fcntl,gzip,hashlib,json,os,stat,tempfile,time
from pathlib import Path
def sha(data):return hashlib.sha256(data).hexdigest()
def syncdir(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def atomic_new(path,data):
    fd,tmp=tempfile.mkstemp(prefix='.compress-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.link(tmp,path)
        syncdir(path.parent)
    finally:os.unlink(tmp)
def eligible(p):
    return p.is_file() and not p.is_symlink() and p.name.startswith('bridge_') and p.suffix=='.json'
def identity(p):
    s=p.lstat()
    if not stat.S_ISREG(s.st_mode):raise ValueError('not regular')
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def compress(p,replace=False):
    p=Path(p)
    if not eligible(p):raise ValueError('ineligible')
    before=identity(p)
    if before[2]>16*1024*1024:raise ValueError('oversized')
    raw=p.read_bytes();json.loads(raw)
    if identity(p)!=before:raise ValueError('changed')
    z=p.with_suffix('.json.gz');m=p.with_suffix('.json.gz.sha256')
    packed=gzip.compress(raw,compresslevel=6,mtime=0)
    if not z.exists():atomic_new(z,packed)
    if z.is_symlink() or gzip.decompress(z.read_bytes())!=raw:raise ValueError('compressed mismatch')
    digest=(sha(raw)+'\n').encode()
    if not m.exists():atomic_new(m,digest)
    if m.is_symlink() or m.read_bytes()!=digest:raise ValueError('digest mismatch')
    if replace:
        if identity(p)!=before or p.read_bytes()!=raw:raise ValueError('source changed')
        p.unlink();syncdir(p.parent)
    return len(raw),z.stat().st_size
def restore(z):
    z=Path(z)
    if not z.name.startswith('bridge_') or not z.name.endswith('.json.gz') or z.is_symlink():raise ValueError('ineligible')
    m=Path(str(z)+'.sha256')
    if m.is_symlink():raise ValueError('digest link')
    raw=gzip.decompress(z.read_bytes())
    if sha(raw)!=m.read_text().strip():raise ValueError('hash mismatch')
    json.loads(raw)
    p=z.with_suffix('')
    if p.exists():
        if p.is_symlink() or p.read_bytes()!=raw:raise ValueError('destination conflict')
    else:atomic_new(p,raw)
    return p
def maintain_archives(directory,replace=False,limit=1,keep=10,min_age=86400):
    directory=Path(directory)
    if not directory.is_dir() or directory.is_symlink():return []
    with (directory/'.archive-compression.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return []
        files=sorted((p for p in directory.glob('bridge_*.json') if eligible(p)),key=lambda p:p.stat().st_mtime_ns,reverse=True)
        out=[]
        for p in reversed(files[keep:]):
            if time.time()-p.stat().st_mtime<min_age:continue
            if not replace and p.with_suffix('.json.gz').exists():continue
            try:out.append((p.name,*compress(p,replace)))
            except (OSError,ValueError,EOFError):continue
            if len(out)>=limit:break
        return out
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--restore',type=Path,required=True)
    print(restore(parser.parse_args().restore))
