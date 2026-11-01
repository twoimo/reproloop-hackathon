"""Host bootstrap smoke, not model exploration or accepted paired replay."""
from pathlib import Path
import argparse,hashlib,json,subprocess,time,uuid,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from reproloop.runtime.owned import png_size,parse_hierarchy
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('state_dir',type=Path);parser.add_argument('apk',type=Path);parser.add_argument('expected_sha256');parser.add_argument('--adb',type=Path,default=Path.home()/'Library/Android/sdk/platform-tools/adb');args=parser.parse_args()
state=args.state_dir.resolve();apk=args.apk.resolve();expected=args.expected_sha256;b=json.loads((state/'bootstrap.json').read_text());assert b['phase']=='READY'
assert hashlib.sha256(apk.read_bytes()).hexdigest()==expected
adb=str(args.adb);prefix=[adb,'-P',str(b['adb_server_port']),'-s',b['serial']]
assert b['serial'].startswith('emulator-') and b['avd_name'].startswith('ReproLoop_')
events=[]
def cmd(args,timeout=20):
 t=time.perf_counter();p=subprocess.run(prefix+args,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout)
 events.append({'argv':args,'elapsed_s':time.perf_counter()-t,'exit':p.returncode,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()})
 if p.returncode:raise RuntimeError(str(args)+': '+p.stderr.decode(errors='replace')[:500])
 return p.stdout

def own():
 assert cmd(['emu','avd','name']).decode().replace('\r\n','\n').strip()==b['avd_name']+'\nOK'
 assert cmd(['shell','cat','/data/local/tmp/reproloop-owner']).decode().strip()==b['owner_id']
 assert cmd(['shell','cat','/proc/sys/kernel/random/boot_id']).decode().strip()==b['avd_boot_id']
try:
 own();print({'install':cmd(['install','-r','-t',str(apk)],60).decode().strip()});own()
 run='native-smoke-'+uuid.uuid4().hex
 args=['shell','am','start','-W','-n','com.tinyburn.reproloop.lab/.MainActivity','--ez','reset_fixture','true','--es','fixture_id','DEV01','--es','run_id',run,'--el','generation','1','--ei','seed','1','--es','layout_variant','A','--es','target_title','Inbox','--es','non_target_title','Archive']
 print({'launch':cmd(args).decode().strip()});own()
 raw=cmd(['shell','run-as','com.tinyburn.reproloop.lab','cat','files/state.json']);obj=json.loads(raw);assert obj['run_id']==run and obj['build_mode']=='faulty' and obj['target_title']=='Inbox' and obj['cancel_count']==0
 (state/'native-initial-state.json').write_bytes(raw)
 png=cmd(['exec-out','screencap','-p']);(state/'native-initial.png').write_bytes(png);w,h=png_size(png)
 cmd(['shell','uiautomator','dump','/data/local/tmp/reproloop-window.xml']);xml=cmd(['exec-out','cat','/data/local/tmp/reproloop-window.xml']);(state/'native-initial.xml').write_bytes(xml)
 try:nodes=parse_hierarchy(xml,w,h);parse={'accepted':True,'nodes':len(nodes),'clickable':[(n.resource_id,n.text) for n in nodes if n.clickable]}
 except Exception as e:parse={'accepted':False,'reason':str(e)}
 result={'mode':'NATIVE_AVD_HOST_SMOKE','model_calls':0,'video_calls':0,'cua_calls':0,'workflow_complete':False,'paired_replay_complete':False,'serial':b['serial'],'run_id':run,'apk_sha256':expected,'screen':[w,h],'hierarchy':parse,'initial_state_validated':True,'commands':events}
 (state/'native-smoke.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='commands'},indent=2))
finally:
 (state/'native-smoke-commands.json').write_text(json.dumps(events,indent=2)+'\n')
