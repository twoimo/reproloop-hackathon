"""Create a fresh task-owned AVD. Never reuse, overwrite or stop an existing one."""
from pathlib import Path
import argparse,hashlib,json,os,re,socket,subprocess,time,uuid

def finalized_config_pins(cfg,created_sha256):
 """Call only after this fresh boot AND owner marker are verified.

 Keep the prelaunch pin as history. The trusted emulator may normalize spacing
 or grow its private data partition during boot. This is not an API for
 re-pinning an established runtime/journal or authenticating a producer.
 """
 if not re.fullmatch(r'[0-9a-f]{64}',created_sha256):raise ValueError('created config SHA-256 required')
 cfg=Path(cfg)
 if cfg.is_symlink()or not cfg.is_file():raise ValueError('regular owned config required')
 return dict(created_config_sha256=created_sha256,config_sha256=hashlib.sha256(cfg.read_bytes()).hexdigest())

def main():
 p=argparse.ArgumentParser();p.add_argument('--direct-config',action='store_true');p.add_argument('--state-dir',required=True);p.add_argument('--sdk',required=True);p.add_argument('--jdk',required=True);p.add_argument('--name',required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args()
 root=Path(a.state_dir).resolve();sdk=Path(a.sdk).resolve();jdk=Path(a.jdk).resolve()
 if not re.fullmatch(r'ReproLoop_[A-Za-z0-9_]{4,60}',a.name):raise ValueError('owned AVD name required')
 if not(5554<=a.port<=5682 and a.port%2==0):raise ValueError('unsupported even console port')
 root.mkdir(parents=True,exist_ok=True);receipt=root/'bootstrap.json'
 if receipt.exists():raise RuntimeError('Existing bootstrap receipt: reconcile it before any new launch')
 for port in(a.port,a.port+1):
  with socket.socket() as s:s.bind(('127.0.0.1',port))
 for d in('avds','emulator-home','android-user'):(root/d).mkdir(exist_ok=True)
 env={k:v for k,v in os.environ.items() if k in('HOME','PATH','TMPDIR','LANG','LC_ALL')}
 env.update(JAVA_HOME=str(jdk),ANDROID_HOME=str(sdk),ANDROID_SDK_ROOT=str(sdk),ANDROID_AVD_HOME=str(root/'avds'),ANDROID_EMULATOR_HOME=str(root/'emulator-home'),ANDROID_USER_HOME=str(root/'android-user'))
 image='system-images;android-34;google_apis_playstore;arm64-v8a'
 if not(sdk/'system-images/android-34/google_apis_playstore/arm64-v8a/system.img').is_file():raise RuntimeError('Required installed public image missing')
 avd=root/'avds'/f'{a.name}.avd'
 if avd.exists():raise RuntimeError('AVD path already exists; no overwrite')
 command=[str(sdk/'cmdline-tools/latest/bin/avdmanager'),'create','avd','-n',a.name,'-p',str(avd),'-k',image]
 if a.direct_config:
  avd.mkdir()
  (root/'avds'/f'{a.name}.ini').write_text(f'avd.ini.encoding=UTF-8\npath={avd}\ntarget=android-34\n')
  image_dir=sdk/'system-images/android-34/google_apis_playstore/arm64-v8a'
  base={'AvdId':a.name,'avd.ini.encoding':'UTF-8','abi.type':'arm64-v8a','hw.cpu.arch':'arm64','image.sysdir.1':str(image_dir)+'/', 'tag.id':'google_apis_playstore','tag.display':'Google Play','hw.gpu.enabled':'yes','hw.gpu.mode':'swiftshader','disk.dataPartition.size':'2G','hw.sdCard':'no','hw.mainKeys':'no','skin.dynamic':'yes','skin.path':'_no_skin','PlayStore.enabled':'true','fastboot.forceColdBoot':'yes'}
  (avd/'config.ini').write_text(''.join(f'{k}={v}\n' for k,v in base.items()))
 else:
  create=subprocess.run(command,input=b'no\n',capture_output=True,timeout=90,env=env)
  if create.returncode:raise RuntimeError('AVD creation rejected: '+create.stderr.decode(errors='replace')[-4000:])
 cfg=avd/'config.ini';text=cfg.read_text();settings={'hw.lcd.width':'720','hw.lcd.height':'1280','hw.lcd.density':'320','hw.ramSize':'2048','hw.cpu.ncore':'2','hw.keyboard':'yes','hw.camera.back':'none','hw.camera.front':'none','hw.audioInput':'no','hw.audioOutput':'no','showDeviceFrame':'no'}
 lines=[l for l in text.splitlines() if l.partition('=')[0].strip() not in settings];cfg.write_text('\n'.join(lines+[f'{k}={v}' for k,v in settings.items()])+'\n')
 data={'schema_version':1,'phase':'CREATED','avd_name':a.name,'serial':f'emulator-{a.port}','owner_id':uuid.uuid4().hex,'config_sha256':hashlib.sha256(cfg.read_bytes()).hexdigest(),'avd_dir':str(avd),'adb_server_port':5037,'image':image,'creation_method':'DIRECT_NATIVE_CONFIG' if a.direct_config else 'AVDMANAGER','created_at':time.time()}
 def save():
  tmp=receipt.with_suffix('.next');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(receipt)
 save();args=[str(sdk/'emulator/emulator'),'-avd',a.name,'-port',str(a.port),'-no-window','-no-audio','-no-boot-anim','-no-snapshot','-gpu','swiftshader','-memory','2048','-cores','2','-camera-back','none','-camera-front','none']
 data.update(phase='STARTING',launch_argv=args);save()
 with(root/'emulator.log').open('ab') as log:proc=subprocess.Popen(args,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 data.update(pid=proc.pid);save();adb=str(sdk/'platform-tools/adb');prefix=[adb,'-P','5037','-s',data['serial']]
 def read(args):
  r=subprocess.run(prefix+args,capture_output=True,timeout=4)
  if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace')[:300])
  return r.stdout.decode().strip()
 deadline=time.monotonic()+120;last='not discovered'
 while time.monotonic()<deadline:
  if proc.poll() is not None:
   data.update(phase='LAUNCH_EXITED',exit_code=proc.returncode);save();raise RuntimeError('Owned emulator exited; inspect owned emulator.log before any retry')
  try:
   name=read(['emu','avd','name']).splitlines()[0]
   if name!=a.name:raise RuntimeError('Unexpected AVD identity')
   if read(['shell','getprop','sys.boot_completed'])=='1':break
  except (RuntimeError,subprocess.TimeoutExpired) as e:last=str(e)
  time.sleep(1)
 else:
  data.update(phase='BOOT_UNKNOWN',last_error=last);save();raise TimeoutError('Boot not confirmed; do not replay launch')
 boot=read(['shell','cat','/proc/sys/kernel/random/boot_id'])
 if not re.fullmatch(r'[0-9a-f-]{36}',boot):raise RuntimeError('Guest boot identity invalid')
 data.update(phase='BOOTSTRAP_VERIFIED',avd_boot_id=boot);save()
 marker=root/'owner-marker.txt';marker.write_text(data['owner_id']+'\n')
 subprocess.run(prefix+['push',str(marker),'/data/local/tmp/reproloop-owner'],check=True,capture_output=True,timeout=10)
 if read(['shell','cat','/data/local/tmp/reproloop-owner'])!=data['owner_id']:raise RuntimeError('Owner marker write unconfirmed')
 data.update(finalized_config_pins(cfg,data['config_sha256']))
 data.update(phase='READY',boot_elapsed_seconds=round(time.time()-data['created_at'],3));save()
 print(json.dumps({k:data[k] for k in('phase','serial','avd_name','owner_id','avd_boot_id','pid','boot_elapsed_seconds')},indent=2))
if __name__=='__main__':main()
