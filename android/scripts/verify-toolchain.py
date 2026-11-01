"""Verify original six byte pins; optional observation report never grants admission."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,platform,re,sys
ROOT=Path(__file__).resolve().parents[1]
TOOLS={
 'kotlin_compiler':('KOTLIN_HOME','lib/kotlin-compiler.jar'),
 'kotlin_stdlib':('KOTLIN_HOME','lib/kotlin-stdlib.jar'),
 'android_jar':('ANDROID_SDK_ROOT','platforms/android-34/android.jar'),
 'd8_jar':('ANDROID_SDK_ROOT','build-tools/34.0.0/lib/d8.jar'),
 'apksigner_jar':('ANDROID_SDK_ROOT','build-tools/34.0.0/lib/apksigner.jar'),
 'aapt2':('ANDROID_SDK_ROOT','build-tools/34.0.0/aapt2'),
}


def digest_file(path):
 with path.open('rb')as stream:
  before=os.fstat(stream.fileno());digest=hashlib.sha256()
  while block:=stream.read(1048576):digest.update(block)
  after=os.fstat(stream.fileno())
 if(before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('file changed during observation')
 return digest.hexdigest()


def version_file(path,key=None):
 try:
  if path.stat().st_size>65536:return None
  text=path.read_text()
  if key:
   rows=[line.partition('=')[2].strip().strip('"')for line in text.splitlines()if line.partition('=')[0].strip()==key]
   text=rows[0] if len(rows)==1 else ''
  text=text.strip()
  return text if re.fullmatch(r'[0-9][0-9A-Za-z._+\-]{0,63}',text)else None
 except(OSError,UnicodeError):return None


def observe(env,lock_path):
 lock_raw=lock_path.read_bytes();lock=json.loads(lock_raw)
 if type(lock)is not dict:raise ValueError('original lock object required')
 expected=lock.get('observed_installed_sha256')
 if type(expected)is not dict or set(expected)!=set(TOOLS)or any(type(v)is not str or re.fullmatch(r'[0-9a-f]{64}',v)is None for v in expected.values()):raise ValueError('original six-pin schema required')
 homes={};errors=[];observed={};mismatches=[]
 for variable in('ANDROID_SDK_ROOT','KOTLIN_HOME'):
  value=env.get(variable,'')
  if not value:errors.append(variable+' is not set')
  elif not Path(value).is_dir():errors.append(variable+' does not name an existing directory')
  else:homes[variable]=Path(value)
 for name,(variable,relative)in TOOLS.items():
  if variable not in homes:continue
  path=homes[variable]/relative
  if not path.is_file():errors.append('missing installed file for '+name+': '+variable+'/'+relative);continue
  try:observed[name]=digest_file(path)
  except(OSError,ValueError):errors.append('unreadable/changed installed file for '+name);continue
  if observed[name]!=expected[name]:mismatches.append(name)
 if lock_path.read_bytes()!=lock_raw:errors.append('original lock changed during observation')
 versions={}
 if'KOTLIN_HOME'in homes:versions['kotlin_build']=version_file(homes['KOTLIN_HOME']/'build.txt')
 if'ANDROID_SDK_ROOT'in homes:versions['build_tools']=version_file(homes['ANDROID_SDK_ROOT']/'build-tools/34.0.0/source.properties','Pkg.Revision')
 if env.get('JAVA_HOME'):versions['jdk']=version_file(Path(env['JAVA_HOME'])/'release','JAVA_VERSION')
 report=dict(schema=1,kind='PRIVATE_TOOLCHAIN_OBSERVATION_NOT_ADMISSION',observed_at=datetime.now(timezone.utc).isoformat(),host=dict(system=platform.system(),machine=platform.machine()),versions=versions,source_lock_sha256=hashlib.sha256(lock_raw).hexdigest(),observed_sha256=observed,original_six_pins_match=not errors and not mismatches and len(observed)==6,mismatches=mismatches,errors=errors,independent_machine='NOT_ESTABLISHED_BY_METADATA',native_authority='NOT_EVALUATED_OR_GRANTED',compatibility='NOT_ESTABLISHED_BY_HASH_MATCH',network_model_device_operations=0,original_lock_written=False)
 return report


def save_observation(path,report):
 path=Path(path).absolute()
 if path.parent!=path.parent.resolve()or not path.parent.is_dir()or any(p.is_symlink()for p in(path.parent,*path.parent.parents)):
  raise ValueError('real existing report parent required')
 fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'wb')as stream:
  stream.write((json.dumps(report,indent=2,sort_keys=True)+'\n').encode());stream.flush();os.fsync(stream.fileno())
 fd=os.open(path.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--record-observed',type=Path,help='new exclusive report, including mismatches/missing prerequisites; never adopts these pins')
 args=parser.parse_args()
 try:
  report=observe(os.environ,ROOT/'toolchain-lock.json')
  if args.record_observed:save_observation(args.record_observed,report)
 except(OSError,ValueError,KeyError):
  print('TOOLCHAIN CHECK FAILED: unreadable lock or report refused; reconcile existing output, never overwrite',file=sys.stderr);return 2
 if report['errors']:
  print('TOOLCHAIN CHECK FAILED: '+report['errors'][0],file=sys.stderr)
  print('No download/install/license acceptance is performed. Set variables to EXISTING installed homes (see docs/FRESH_REPRODUCTION.md).',file=sys.stderr);return 2
 if report['mismatches']:
  print('Tool pin mismatch: '+report['mismatches'][0],file=sys.stderr);return 1
 print('PASS six observed installed tool byte pins; no compatibility/runtime claim')
 return 0


if __name__=='__main__':raise SystemExit(main())
