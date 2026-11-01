"""Bounded trusted-host subprocess runner. Never a model-exposed command tool."""
import os,selectors,signal,subprocess,time
from .runtime.owned import CommandResult
class SystemClock:
 def monotonic(self):return time.monotonic()
 def sleep(self,seconds):time.sleep(seconds)
class BoundedRunner:
 def __call__(self,argv,timeout,max_output):
  if not isinstance(argv,tuple) or not argv or not all(type(v)is str and '\x00' not in v for v in argv):raise ValueError('fixed argv required')
  if not 0<timeout<=60 or not 0<max_output<=32*1024*1024:raise ValueError('runner bound')
  env={k:v for k,v in os.environ.items() if k in('HOME','PATH','TMPDIR','LANG','LC_ALL','PYTHONHOME')}
  p=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env=env)
  sel=selectors.DefaultSelector();out=bytearray();err=bytearray();sel.register(p.stdout,selectors.EVENT_READ,out);sel.register(p.stderr,selectors.EVENT_READ,err);end=time.monotonic()+timeout
  try:
   while sel.get_map():
    remaining=end-time.monotonic()
    if remaining<=0:raise TimeoutError('owned subprocess deadline')
    for key,_ in sel.select(min(remaining,.05)):
     chunk=os.read(key.fileobj.fileno(),65536)
     if not chunk:sel.unregister(key.fileobj);continue
     key.data.extend(chunk)
     if len(out)+len(err)>max_output:raise ValueError('owned subprocess output bound')
   remaining=end-time.monotonic()
   if remaining<=0:raise TimeoutError('owned subprocess deadline')
   code=p.wait(timeout=remaining)
   return CommandResult(code,bytes(out),bytes(err))
  finally:
   if p.poll()is None:
    os.killpg(p.pid,signal.SIGKILL);p.wait()
   sel.close();p.stdout.close();p.stderr.close()
