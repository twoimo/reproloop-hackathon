#!/usr/bin/env python3
"""Private, local-only evidence film. No device/model/network operations."""
import argparse, concurrent.futures, hashlib, json, pathlib, shutil, subprocess, sys, platform
import contextlib, ctypes, os, re, tempfile
from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version
FF='/opt/homebrew/bin/ffmpeg'; FP='/opt/homebrew/bin/ffprobe'
FONT='/System/Library/Fonts/Supplemental/Arial.ttf'; BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
W,H,FPS=1920,1080,24
BG='#EEF3F8'; WHITE='#FFFFFF'; FG='#10233F'; COBALT='#245CEC'
MUTED='#526278'; LINE='#D5DFEB'; AMBER='#98600B'; ROSE='#A63756'
VIDEO_BOX=(1210,154,1848,886)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def js(p,d): p.write_text(json.dumps(d,indent=2)+'\n')
def run(a): return subprocess.run(a,check=True,capture_output=True)
def font(n,b=False): return ImageFont.truetype(BOLD if b else FONT,n)
def wrap(draw,text,n,width,b=False):
 words=text.split(); lines=[]; line=''
 for word in words:
  trial=(line+' '+word).strip()
  if draw.textlength(trial,font=font(n,b))>width and line:lines.append(line);line=word
  else:line=trial
 if line:lines.append(line)
 return lines

def contain(im, p, box):
 # Preserve the complete original frame and its aspect ratio, never crop/stretch.
 pic=Image.open(p).convert('RGB'); x0,y0,x1,y1=box
 scale=min((x1-x0)/pic.width,(y1-y0)/pic.height)
 size=(max(1,round(pic.width*scale)),max(1,round(pic.height*scale)))
 pic=pic.resize(size,Image.Resampling.LANCZOS)
 im.paste(pic,(x0+(x1-x0-size[0])//2,y0+(y1-y0-size[1])//2))

def text_block(d,texts,box,n=36,b=False,color=FG,gap=18):
 x0,y0,x1,y1=box
 # Fit the text to a reserved band, rather than allowing evidence/footer overlap.
 for size in range(n,27,-1):
  rows=[wrap(d,t,size,x1-x0,b) for t in texts]
  step=round(size*1.28); height=sum(len(r)*step for r in rows)+gap*(len(rows)-1)
  if height<=y1-y0 and all(d.textlength(line,font=font(size,b))<=x1-x0 for row in rows for line in row):break
 else:raise ValueError('Text exceeds reserved presentation band: '+repr(texts))
 y=y0
 for row in rows:
  for line in row:
   assert d.textlength(line,font=font(size,b))<=x1-x0, 'Unbreakable text exceeds band'
   d.text((x0,y),line,font=font(size,b),fill=color);y+=step
  y+=gap
 return y-gap

WORKBENCH_SOURCE_PATHS=frozenset(('ui/index.html','ui/console.css','ui/app.js','ui/adapter.js',
                                  'ui/recorded-demo.js','ui/fixtures/recorded-case.json',
                                  'ui/fixtures/recorded-assets.json'))

def sanitized_receipt(receipt, original_bytes, capture_hash):
 # Values as well as keys are allowlisted: free-form provenance can contain PII.
 if (not isinstance(receipt,dict)
     or receipt.get('kind')!='PRIVATE_RECORDED_WORKBENCH_SOFTWARE_CAPTURE'
     or receipt.get('capture_sha256')!=capture_hash
     or receipt.get('screenshot_sha256',capture_hash)!=capture_hash
     or receipt.get('not_a_new_native_or_Meta_run') is not True
     or receipt.get('not_producer_attestation') is not True):
  raise ValueError('Workbench receipt must bind capture_sha256 and declare recorded software-only, non-attested capture')
 safe={'schema':1,'kind':receipt['kind'],'capture_sha256':capture_hash,
       'screenshot_sha256':capture_hash,'not_a_new_native_or_Meta_run':True,
       'not_producer_attestation':True,
       'role':'SANITIZED_DERIVATIVE_NOT_ORIGINAL_RECEIPT',
       'evidence_class':'RECORDED_WORKBENCH_NOT_NATIVE_EVIDENCE',
       'original_receipt':{'sha256':hashlib.sha256(original_bytes).hexdigest(),
                           'bytes':len(original_bytes),'role':'ORIGINAL_INPUT_NOT_DISTRIBUTED'},
       'source_hashes_verification':'DECLARED_ONLY_NOT_INDEPENDENTLY_VERIFIED'}
 for key in ('source_revision','source_commit','renderer_sha256','base_revision',
             'committed_snapshot_matching_captured_bytes'):
  if key not in receipt:continue
  value=receipt[key]
  if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',value):
   raise ValueError('Workbench provenance revision/hash must be lowercase hexadecimal (40 or 64 characters)')
  safe[key]=value
 if 'source_files' in receipt:
  declared=receipt['source_files'];files=[];seen=set()
  if not isinstance(declared,list):raise ValueError('Workbench source_files must be a list')
  for item in declared:
   if not isinstance(item,dict):raise ValueError('Workbench source_files entries must be objects')
   name=item.get('path');digest=item.get('sha256')
   if not isinstance(name,str) or name not in WORKBENCH_SOURCE_PATHS:
    raise ValueError('Workbench source_files contains a non-allowlisted path')
   if name in seen:raise ValueError('Workbench source_files contains a duplicate path')
   if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
    raise ValueError('Workbench source_files SHA-256 must be 64 lowercase hexadecimal characters')
   seen.add(name);files.append({'path':name,'sha256':digest})
  if seen!=WORKBENCH_SOURCE_PATHS:
   raise ValueError('Workbench source_files must declare exactly the seven allowlisted UI files')
  safe['source_files']=files
 # capture and captured_at are deliberately omitted: filenames/free-form metadata
 # are not required to bind provenance; timestamps are not authenticated here.
 return safe

def unused_path(value):
 value=pathlib.Path(os.path.abspath(value))
 if value.exists() or value.is_symlink():raise FileExistsError(str(value))
 for parent in value.parents:
  if parent.is_symlink():raise ValueError('Symlink output ancestor: '+str(parent))
 return value

def publish_directory(staging, final):
 # Plain rename may replace a concurrently created empty directory. Fail closed
 # unless the host has an atomic no-replace directory rename primitive.
 libc=ctypes.CDLL(None,use_errno=True)
 if sys.platform=='darwin':
  result=libc.renamex_np(os.fsencode(staging),os.fsencode(final),ctypes.c_uint(4)) # RENAME_EXCL
 elif sys.platform.startswith('linux') and hasattr(libc,'renameat2'):
  result=libc.renameat2(-100,os.fsencode(staging),-100,os.fsencode(final),1) # RENAME_NOREPLACE
 else:raise OSError('Atomic no-replace directory publication unavailable on this host')
 if result:
  code=ctypes.get_errno()
  raise OSError(code,os.strerror(code),str(final))

@contextlib.contextmanager
def render_workspace(output, scratch):
 final=unused_path(output);tmp=unused_path(scratch)
 if final==tmp or final in tmp.parents or tmp in final.parents:
  raise ValueError('Output and scratch must be separate, non-nested paths')
 # Parents must exist; never traverse/create unknown symlink-bearing trees.
 staging=None;created_scratch=False
 try:
  tmp.mkdir();created_scratch=True
  staging=pathlib.Path(tempfile.mkdtemp(prefix='.'+final.name+'-staging-',dir=final.parent))
  yield staging,tmp
  publish_directory(staging,final)
 finally:
  if staging is not None and staging.exists():shutil.rmtree(staging)
  if created_scratch:shutil.rmtree(tmp)

def distribution_manifest(out, sources):
 original_files={v['file'] for v in sources.values() if v.get('role')!='SANITIZED_DERIVATIVE_NOT_ORIGINAL_RECEIPT'}
 roles={'safe-aggregates.json':'SANITIZED_AGGREGATE_CLAIMS','safe-evidence.json':'SANITIZED_EVIDENCE_SUMMARY',
        'source-manifest.json':'SOURCE_REFERENCES','generation-manifest.json':'GENERATION_METADATA',
        'storyboard.json':'EDITED_STORYBOARD','STORYBOARD.md':'EDITED_STORYBOARD',
        'ReproLoop_180s.srt':'EDITED_CAPTIONS','REHEARSAL.md':'AUTOMATED_REHEARSAL_REPORT',
        'ffprobe-validation.json':'DECODE_METADATA','CONTACT_SHEET.jpg':'EDITED_OUTPUT_REVIEW',
        'ReproLoop_Private_180s_1080p.mp4':'EDITED_SILENT_FILM'}
 files=[]
 for p in sorted(out.rglob('*')):
  if p.is_symlink():raise ValueError('Unexpected symlink in distribution')
  if not p.is_file():continue
  name=p.relative_to(out).as_posix()
  if name=='distribution-manifest.json':continue
  role=('SANITIZED_DERIVATIVE_NOT_ORIGINAL_RECEIPT' if name=='captures/workbench-source-receipt.json'
        else 'ORIGINAL_MEDIA_COPY' if name in original_files and name.startswith('captures/')
        else 'EDITED_SCENE_REVIEW' if name.startswith('review/') else roles.get(name))
  if role is None:raise ValueError('Unclassified distribution file: '+name)
  files.append({'file':name,'bytes':p.stat().st_size,'sha256':sha(p),'role':role})
 js(out/'distribution-manifest.json',{'schema':1,'role':'FINAL_DISTRIBUTION_INVENTORY',
    'self_hash':'EXCLUDED_TO_AVOID_CYCLE','files':files,
    'limits':['Hashes bind bytes, not media or producer authenticity',
              'Original source references are in source-manifest.json; edited outputs are not new native evidence']})

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--session',type=pathlib.Path,required=True)
 ap.add_argument('--out',type=pathlib.Path,required=True)
 ap.add_argument('--scratch',type=pathlib.Path,required=True)
 ap.add_argument('--workbench-image',type=pathlib.Path,help='Actual recorded product UI screenshot, paired with source receipt')
 ap.add_argument('--workbench-source-manifest',type=pathlib.Path,help='Exact JSON source/hash receipt for the workbench screenshot')
 a=ap.parse_args()
 if bool(a.workbench_image)!=bool(a.workbench_source_manifest):
  ap.error('--workbench-image and --workbench-source-manifest must be supplied together')
 # Validate optional inputs before creating output. Receipt fields are declarations,
 # not a claim that this renderer verified UI source files or native execution.
 workbench_receipt=None
 if a.workbench_image:
  original_bytes=a.workbench_source_manifest.read_bytes()
  try:workbench_receipt=sanitized_receipt(json.loads(original_bytes),original_bytes,sha(a.workbench_image))
  except (ValueError,TypeError) as exc:ap.error(str(exc))
  with Image.open(a.workbench_image) as check:check.verify()
 with render_workspace(a.out,a.scratch) as (out,tmp):
  result=render(a,out,tmp,workbench_receipt)
 result['output']=str(a.out/'ReproLoop_Private_180s_1080p.mp4')
 print(json.dumps(result))

def render(a,out,tmp,workbench_receipt):
 renderer_path=pathlib.Path(__file__).resolve()
 git_head=subprocess.run(['git','-C',str(renderer_path.parent),'rev-parse','HEAD'],capture_output=True,text=True)
 presentation={'source_revision':git_head.stdout.strip() if git_head.returncode==0 else None,
               'renderer_sha256':sha(renderer_path),
               'revision_scope':'presentation checkout HEAD; exact renderer bytes bound separately, not newly native-executed'}
 (out/'captures').mkdir();(out/'review').mkdir()
 root=a.session/'tmp/final-native-v4obs1/FINAL-C-v4obs1';view=a.session/'artifacts/ReproLoop_Final_Viewer'; sources={}
 aggregate_path=pathlib.Path(__file__).with_name('safe-aggregates.json');aggregates=json.loads(aggregate_path.read_text());pilot=aggregates['original_pilot'];final=aggregates['final_cohort'];per_final=aggregates['per_final'];budget=aggregates['budget']
 assert aggregates['schema']==1 and pilot['id']=='v3' and final['id']=='v4obs1-FINAL'
 assert pilot['successes']<pilot['target_minimum'] and pilot['successes']+pilot['known_failed']+pilot['unknown']==pilot['attempted']==pilot['denominator']
 assert final['successes']+final['known_failed']+final['unknown']==final['attempted']==final['denominator']
 assert budget['upload_price']=='UNPRICED' and budget['not_final_billing']
 shutil.copy2(aggregate_path,out/'safe-aggregates.json');sources['aggregate-claims']={'file':'safe-aggregates.json','sha256':sha(aggregate_path),'bytes':aggregate_path.stat().st_size,'source_ref':'safe derived pilot, FINAL and read-only ledger aggregate; not attestation'}
 def asset(p,label):
  name=label+p.suffix;dst=out/'captures'/name;shutil.copy2(p,dst); sources[label]={'file':'captures/'+name,'sha256':sha(p),'bytes':p.stat().st_size,'source_ref':'FINAL-C/'+str(p.relative_to(root)) if p.is_relative_to(root) else 'clean-viewer/'+p.name};return label
 vid=asset(view/'FINAL-C-recorded-source.mp4','source-video')
 workbench=None
 if workbench_receipt is not None:
  workbench='workbench-image'; receipt_id='workbench-source-receipt'
  dst=out/'captures'/('workbench-image'+a.workbench_image.suffix);shutil.copy2(a.workbench_image,dst)
  sources[workbench]={'file':'captures/'+dst.name,'sha256':sha(dst),'bytes':dst.stat().st_size,
                      'source_ref':'recorded-workbench/software-capture',
                      'role':'ORIGINAL_MEDIA_COPY','evidence_class':'RECORDED_WORKBENCH_NOT_NATIVE_EVIDENCE'}
  dst=out/'captures/workbench-source-receipt.json';js(dst,workbench_receipt)
  sources[receipt_id]={'file':'captures/'+dst.name,'sha256':sha(dst),'bytes':dst.stat().st_size,
                      'source_ref':'recorded-workbench/sanitized-declared-source-hash-receipt',
                      'role':'SANITIZED_DERIVATIVE_NOT_ORIGINAL_RECEIPT',
                      'original_receipt':workbench_receipt['original_receipt'],
                      'evidence_class':'RECORDED_WORKBENCH_NOT_NATIVE_EVIDENCE'}
  sources[workbench]['source_manifest_id']=receipt_id
  sources[workbench]['source_manifest_sha256']=sources[receipt_id]['sha256']
 if workbench:assert sources[workbench]['sha256']==workbench_receipt['capture_sha256'], 'Capture changed while copying'
 presentation['workbench_capture_sha256']=sources[workbench]['sha256'] if workbench else None
 presentation['workbench_source_manifest_sha256']=sources['workbench-source-receipt']['sha256'] if workbench else None
 presentation['workbench_original_receipt_sha256']=workbench_receipt['original_receipt']['sha256'] if workbench else None
 source_probe=json.loads(run([FP,'-v','error','-show_format','-of','json',str(out/sources[vid]['file'])]).stdout);source_duration=float(source_probe['format']['duration']);playback_factor=source_duration/18
 assert source_duration>0 and playback_factor>0
 summary=json.loads((root/'summary.json').read_text());export=json.loads((root/'model/semantic-export.json').read_text());exp=json.loads((root/'model/exploration-summary.json').read_text())
 cua=[asset(root/'evidence'/f"{x['receipt']['evidence']['png_sha256']}.png",f'cua-{i+1}') for i,x in enumerate(exp['attempts'])]
 controls={};safe={'case':'FINAL-C','device_alias':'LAB-ANDROID-1','model':'muse-spark-1.3','source_revision':summary['source_commit'],'export_sha256':summary['export_sha256'],'fixture_sha256':summary['fixture_sha256'],'build_sha256':summary['build_sha256'],'semantic_steps':export['steps'],'model_calls':summary['model_calls'],'read_only_observations':summary['read_only_observations'],'controls':{}}
 for kind in ['faulty','fixed']:
  p=root/(kind+'-replay.json');d=json.loads(p.read_text());t=root/'evidence'/f"{d['trace_sha256']}.trace.json";trace=json.loads(t.read_text())
  assert d['script_sha256']==summary['export_sha256'] and d['model_calls']==0 and d['complete']
  controls[kind]=[asset(root/'evidence'/f"{x['receipt']['evidence']['png_sha256']}.png",f'{kind}-{i+1}') for i,x in enumerate(trace['steps'])]
  safe['controls'][kind]={'model_calls':d['model_calls'],'complete':d['complete'],'failure_observed':d['oracle_run']['failure_observed'],'script_sha256':d['script_sha256'],'oracle':'cancel_preserves_stored_title','source_replay_sha256':sha(p),'source_trace_sha256':sha(t)}
 safe['aggregate_claims_sha256']=sha(aggregate_path)
 assert(summary['model_calls'],summary['read_only_observations'])==(per_final['model_calls'],per_final['read_only_observations'])
 js(out/'safe-evidence.json',safe)
 entries=[]
 def seg(end,title,body,caption,mode='RECORDED META',image=None,extra='',kind='single'):
  start=entries[-1]['end'] if entries else 0;entries.append(dict(start=start,end=end,title=title,body=body,caption=caption,mode=mode,image=image,extra=extra,kind=kind))
 seg(18,'Cancel should mean cancel.',['A bug video is not a regression test.','Release → Today → Cancel','Expected: keep Release. Actual: Today.'],'This self-owned synthetic app saves the draft title after Cancel.','RECORDED SOURCE VIDEO',vid,f'Original recording • {playback_factor:.3f}x playback • no audio', 'video')
 if workbench:
  seg(28,'One Cancel.\nTwo controls.',['Saved product workbench.','Read only. No new device or model run.','UI capture, not native evidence.'],
      'Recorded product workbench: saved controls, not a new device or Meta run.',mode='RECORDED WORKBENCH',image=workbench,
      extra='Software capture + source receipt hash-bound • not producer or OS attestation',kind='workbench')
 else:
  seg(28,'Start with the real recording.',['Meta muse-spark-1.3','VIDEO + 12 uniform frames','Native pointer pixels + temporal OCR'],'The recorded Meta input combines video, uniform frames, pointer pixels and OCR.',image=cua[0],extra='FINAL-C • source SHA-256 afd7f11e • LAB-ANDROID-1')
 seg(38,'A candidate, not a verdict.',['Meta muse-spark-1.3: VIDEO + 12 uniform frames.','Native pointer pixels + temporal OCR.','Proposed workflow; separate Cancel-state oracle.'],'Model intent proposes actions. A separate predeclared oracle checks the result.',image=cua[1],extra='No new inference during this demo')
 for i,(end,title,body) in enumerate([(46,'01  Select the task.','Fresh screenshot → native pixel input'),(53,'02  Open Rename.','Fresh screenshot, not copied video coordinates'),(60,'03  Set the draft to Today.','Accepted input checked by fresh readback'),(67,'04  Press Cancel.','Four native CUA inputs accepted')]):
  seg(end,title,[body,'Recorded CUA: 4 model calls total.'],f'Recorded CUA step {i+1}: '+['select the task.','open Rename.','choose Today.','press Cancel.'][i],image=cua[i],extra='RECORDED FRAME SEQUENCE; transitions omitted')
 seg(75,'The title changed anyway.',['Fault candidate observed.','A model saying “done” is not proof.','Fresh faulty/fixed controls are still required.'],'The title is Today after Cancel. The control pair is still required.',image=cua[3],extra='RECORDED FRAME SEQUENCE; transitions omitted')
 seg(87,'Judge persisted state + events.',['Oracle: cancel_preserves_stored_title','Faulty replay: completed; failure = true.','Not a screenshot-similarity score.'],'The independent persisted-state and event oracle reports the faulty signal.',mode='RECORDED NO-MODEL REPLAY',image=controls['faulty'][3],extra='Saved oracle summary • actual replay capture')
 seg(100,'Keep the evidence boundary clear.',['FINAL-C: sampled pointer context.','Consistent context, not causal proof.','Read-only observations used: 0.'],'Sampled-context consistency is not physical-tap proof. The optional read-only branch was unused.',image=cua[1],extra='Saved-frame montage, not end-to-end elapsed time')
 seg(108,'Export semantics once.',['Target task: Release','Rename → Today → Cancel','Same export on both fresh controls.'],'Export four semantic steps once. Replay the exact same export on fresh faulty and fixed builds.',mode='RECORDED NO-MODEL REPLAY',image=controls['faulty'][0],extra='Export 0f2185d9 • fixture 4c557c97 • model calls 0')
 for i,(end,action) in enumerate([(114,'Select task'),(120,'Open Rename'),(125,'Choose Today'),(130,'Cancel')]):
  seg(end,f'Faulty control  {i+1}/4',[action,'Fresh reset • model calls 0','Failure signal: true after completion.'],f'Faulty model-free replay: {action.lower()}.',mode='RECORDED NO-MODEL REPLAY',image=controls['faulty'][i],extra='RECORDED FRAME SEQUENCE; transitions omitted')
 for i,(end,action) in enumerate([(136,'Select task'),(142,'Open Rename'),(147,'Choose Today'),(152,'Cancel')]):
  seg(end,f'Fixed control  {i+1}/4',[action,'Same export • fresh reset • model calls 0','Developer-supplied, AI-assisted fix; not ReproLoop repair.'],f'Fixed model-free replay: {action.lower()}.',mode='RECORDED NO-MODEL REPLAY',image=controls['fixed'][i],extra='RECORDED FRAME SEQUENCE; transitions omitted')
 seg(158,'Same test. Different outcome.',['FAULTY: Today • failure true','FIXED: Release • failure false','Both workflows completed.'],'Developer-supplied, AI-assisted fix, not ReproLoop repair. Faulty fails; fixed keeps Release.',mode='RECORDED NO-MODEL REPLAY',image=[controls['faulty'][3],controls['fixed'][3]],extra='Same export 0f2185d9 • builds 5b7e27d2 / 4bcd2374',kind='split')
 seg(166,'Preserve both result cohorts.',[f"Original v3 pilot: {pilot['successes']}/{pilot['denominator']}; target ≥{pilot['target_minimum']}/{pilot['denominator']} missed.",f"{pilot['known_failed']} original failures remain.",f"Separate v4obs1 FINAL: {final['successes']}/{final['denominator']} pairs."],'Original pilot: two of five, below target. Separate FINAL: three of three correlated variants.',mode='RECORDED RESULTS',extra='One F01 family • three correlated variants • not independent bugs',kind='wide')
 seg(172,'Bounded evidence. Real limits.',[f"Each FINAL: {per_final['model_calls']} calls, {per_final['accepted_inputs']} inputs, {per_final['control_runs']} controls.",f"Cumulative: {budget['inference_calls']}/{budget['call_cap']} calls; ${budget['known_token_fees_nano_usd']/1e9:.6f} token fees.",f"Uploads {budget['upload_price']}; no generic accuracy claim."],'Each FINAL case used five model calls and two model-free controls. Upload fees remain unpriced.',mode='RECORDED RESULTS',extra='Cumulative fees include earlier failed conditions; not final billing',kind='wide')
 seg(180,'A record you can inspect.',['RECORDED PROTOTYPE','No production certification.','Generalization not evaluated.'],'Recorded prototype. No production certification. Generalization has not been evaluated.',mode='RECORDED EVIDENCE / LIMITED',extra='Byte integrity is not producer, physical-tap, timestamp or OS attestation.',kind='wide')
 assert len(entries)==23 and [e['end'] for e in entries]==[18,28,38,46,53,60,67,75,87,100,108,114,120,125,130,136,142,147,152,158,166,172,180]
 # A sanitized, full-hash mapping retains identities, never original host paths or owners.
 for e in entries:
  e['source_ids']=[e['image']] if isinstance(e['image'],str) else (e['image'] or [])
  if e['start']in(158,166):e['source_ids'].append('aggregate-claims')
  if e['kind']=='workbench':e['source_ids'].append('workbench-source-receipt')
 js(out/'storyboard.json',entries);js(out/'source-manifest.json',{'schema':2,'source_revision':summary['source_commit'],'source_revision_scope':'historical original-native-source, not current presentation','original_native_source_revision':summary['source_commit'],'presentation':presentation,'sources':sources,'segments':[{'start':e['start'],'end':e['end'],'source_ids':e['source_ids'],'presentation':e['kind'],'mode':e['mode']} for e in entries],'limits':['No producer or native attestation','No fake touches or physical-tap timestamps','Native sequences use saved original pixels; static holds omit transitions; optional workbench is a separately labeled software screenshot','No new model/native/network calls'],'safe_summary_source_sha256':sha(root/'summary.json')})
 def stamp(t):return f'{t//3600:02}:{t%3600//60:02}:{t%60:02},000'
 srt='\n\n'.join(f"{i+1}\n{stamp(e['start'])} --> {stamp(e['end'])}\n{e['caption']}" for i,e in enumerate(entries))+'\n';(out/'ReproLoop_180s.srt').write_text(srt)
 md=['# Private 180-second storyboard','All timings are edited presentation time, not native execution time.','']
 slidepaths=[]
 for i,e in enumerate(entries):
  im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
  d.rectangle((0,0,W,7),fill=COBALT)
  d.text((64,32),'ReproLoop',font=font(34,True),fill=FG)
  d.text((281,42),'BUG VIDEO / SAVED REPLAY',font=font(20),fill=MUTED)
  mode_width=d.textlength(e['mode'],font=font(22,True))+36
  d.rounded_rectangle((W-64-mode_width,29,W-64,77),radius=12,fill=WHITE,outline=LINE)
  d.text((W-46-mode_width,39),e['mode'],font=font(22,True),fill=COBALT)
  d.line((64,100,W-64,100),fill=LINE,width=2)
  d.text((64,113),'F01 / SELF-OWNED SYNTHETIC APP',font=font(20,True),fill=MUTED)
  if e['kind']=='split':
   text_block(d,[e['title']],(64,155,1856,225),n=56,b=True)
   for j,label in enumerate(e['image']):
    x=64+j*912;accent=[ROSE,COBALT][j]
    d.rounded_rectangle((x,246,x+880,888),radius=22,fill=WHITE,outline=LINE,width=2)
    d.rounded_rectangle((x+24,270,x+425,318),radius=10,fill=['#FCEEF2','#ECF1FF'][j])
    d.text((x+40,279),['FAULTY BUILD','FIXED CONTROL'][j],font=font(24,True),fill=accent)
    d.text((x+32,360),['Today','Release'][j],font=font(64,True),fill=accent)
    text_block(d,[['failure = true','Cancel saved the edit.'],['failure = false','Cancel kept the title.']][j],(x+32,457,x+412,640),n=32)
    text_block(d,[['Workflow completed.','Same semantic export.'],['Workflow completed.','Developer-supplied,','AI-assisted fix.']][j],(x+32,702,x+423,864),n=28,color=MUTED,gap=7)
    contain(im,out/sources[label]['file'],(x+466,274,x+852,866))
  elif e['kind']=='wide' and e['start']==158:
   text_block(d,[e['title']],(64,155,1856,236),n=56,b=True)
   for j,(label,result,detail) in enumerate([
       ('ORIGINAL v3 PILOT',f"{pilot['successes']}/{pilot['denominator']}",f"Target ≥{pilot['target_minimum']}/{pilot['denominator']} missed. {pilot['known_failed']} failures remain."),
       ('SEPARATE v4obs1 FINAL',f"{final['successes']}/{final['denominator']}",'One F01 family. Three correlated variants.')]):
    x=64+j*912;accent=[ROSE,COBALT][j]
    d.rounded_rectangle((x,286,x+880,838),radius=22,fill=WHITE,outline=LINE,width=2)
    d.text((x+40,324),label,font=font(29,True),fill=accent)
    d.text((x+40,392),result,font=font(144,True),fill=FG)
    text_block(d,[detail,'Not pooled. No general accuracy claim.'],(x+40,635,x+828,800),n=34,color=MUTED)
  else:
   wide=e['kind']=='wide';work=e['kind']=='workbench'
   right=1856 if wide else (590 if work else 1114)
   title_end=text_block(d,e['title'].split('\n'),(64,173,right,389),n=62 if wide else 58,b=True,gap=0)
   if wide:
    for k,text in enumerate(e['body']):
     y=332+k*172;accent=AMBER if e['start']==166 and k==2 else COBALT
     d.rounded_rectangle((64,y,1856,y+136),radius=18,fill=WHITE,outline=LINE,width=2)
     d.rounded_rectangle((64,y,72,y+136),radius=4,fill=accent)
     text_block(d,[text],(100,y+27,1818,y+119),n=40,b=(k==0),color=accent if e['start']==166 and k==2 else FG)
   else:
    text_block(d,e['body'],(68,title_end+32,right,857),n=36,gap=28)
   if e['kind'] in ('single','video','workbench'):
    box=(626,154,1856,886) if work else VIDEO_BOX
    x0,y0,x1,y1=box
    d.rounded_rectangle((x0-14,y0-14,x1+14,y1+14),radius=22,fill=WHITE,outline=LINE,width=2)
    if e['kind']!='video':contain(im,out/sources[e['image']]['file'],box)
  # Quiet provenance and a separate high-contrast caption band; never over media.
  extra=wrap(d,e['extra'],23,1784)
  assert len(extra)<=2
  for j,line in enumerate(extra):d.text((65,912+j*28),line,font=font(23),fill=MUTED)
  d.rectangle((0,974,W,1080),fill=WHITE);d.line((0,974,W,974),fill=LINE,width=2)
  cap=wrap(d,e['caption'],32,1784);assert len(cap)<=2
  for j,line in enumerate(cap):d.text((64,988+j*40),line,font=font(32,True),fill=FG)
  p=tmp/f'slide-{i:02}.png';im.save(p);slidepaths.append(p)
  # Representative originals for the capture review board.
  im.resize((960,540)).save(out/'review'/f'{i:02}-{e["start"]:03}s.jpg',quality=88)
  md += [f"## {e['start']:03}–{e['end']:03}s | {e['title']}",f"Mode: {e['mode']}. {e['extra']}",*e['body'],'Caption: '+e['caption'],'']
 (out/'STORYBOARD.md').write_text('\n'.join(md))
 def encode(i):
  e=entries[i];dur=e['end']-e['start'];dst=tmp/f'part-{i:02}.mp4';args=[FF,'-hide_banner','-loglevel','error','-y','-loop','1','-framerate',str(FPS),'-i',str(slidepaths[i])]
  if e['kind']=='video':
   args+=['-i',str(out/sources[vid]['file']),'-filter_complex',f'[1:v]setpts=(PTS-STARTPTS)/{playback_factor:.10f},scale=638:732:force_original_aspect_ratio=decrease,pad=638:732:(ow-iw)/2:(oh-ih)/2:color=white,fps=24[v];[0:v][v]overlay=1210:154:shortest=0[out]','-map','[out]']
  else:args+=['-map','0:v']
  args+=['-frames:v',str(dur*FPS),'-r',str(FPS),'-an','-c:v','libx264','-preset','ultrafast','-crf','20','-pix_fmt','yuv420p','-threads','2',str(dst)];run(args);return dst
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: parts=list(pool.map(encode,range(len(entries))))
 concat=tmp/'parts.txt';concat.write_text(''.join(f"file '{p}'\n" for p in parts));film=out/'ReproLoop_Private_180s_1080p.mp4'
 run([FF,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-map','0:v:0','-c','copy','-an','-movflags','+faststart',str(film)])
 probe=json.loads(run([FP,'-v','error','-count_frames','-show_format','-show_streams','-of','json',str(film)]).stdout);js(out/'ffprobe-validation.json',{'format':{k:probe['format'][k] for k in ['format_name','duration','size']},'streams':[{k:s[k] for k in ['index','codec_type','codec_name','pix_fmt','width','height','r_frame_rate','nb_read_frames','duration'] if k in s} for s in probe['streams']]})
 v=probe['streams'][0];assert len(probe['streams'])==1 and v['codec_type']=='video' and v['codec_name']=='h264' and v['pix_fmt']=='yuv420p' and v['r_frame_rate']=='24/1' and v['width']==W and v['height']==H and v['nb_read_frames']=='4320' and float(probe['format']['duration'])==180.0
 js(out/'generation-manifest.json',{'original_native_source_revision':summary['source_commit'],'presentation':presentation,'source_manifest_sha256':sha(out/'source-manifest.json'),'python':platform.python_version(),'pillow':pillow_version,'ffmpeg':run([FF,'-version']).stdout.decode().splitlines()[0],'ffprobe':run([FP,'-version']).stdout.decode().splitlines()[0],'renderer_sha256':sha(pathlib.Path(__file__)),'aggregate_claims_sha256':sha(aggregate_path),'source_video_duration_seconds':source_duration,'source_video_playback_factor':playback_factor,'video_sha256':sha(film),'duration_seconds':180,'resolution':[W,H],'fps':FPS,'frames':4320,'audio_streams':0,'new_native_calls':0,'new_model_calls':0,'public_uploads':0,'human_novice_readthrough':'NOT_DONE','no_media_attestation':True})
 # Extract output frames, not just source slide images, at each scene midpoint.
 for i,e in enumerate(entries):run([FF,'-hide_banner','-loglevel','error','-y','-ss',str((e['start']+e['end'])/2),'-i',str(film),'-frames:v','1','-vf','scale=640:360',str(tmp/f'actual-{i:02}.jpg')])
 contact=Image.new('RGB',(1920,((len(entries)+2)//3)*390),BG);dc=ImageDraw.Draw(contact)
 for i,e in enumerate(entries):
  x=i%3*640;y=i//3*390;contact.paste(Image.open(tmp/f'actual-{i:02}.jpg'),(x,y));dc.text((x+12,y+365),f"{e['start']:03}-{e['end']:03}s",font=font(19),fill=FG)
 contact.save(out/'CONTACT_SHEET.jpg',quality=90)
 # Check SRT pacing, structural labels, safe identities and all asset hashes.
 cps=max(len(e['caption'])/(e['end']-e['start']) for e in entries)
 assert cps<22 and all(sha(out/s['file'])==s['sha256'] for s in sources.values())
 report=f'''# Automated local rehearsal check\n\nPASS: 180.000 seconds; 1920×1080; H.264 yuv420p; 24fps; 4,320 decoded frames; no audio streams.\n\n- {len(entries)} segments cover 0–180s contiguously. English captions are burned in and supplied as SRT.\n- Caption peak reading rate: {cps:.2f} characters/second (automated threshold <22); large 32px caption baseline.\n- One actual source MP4 plays at disclosed {playback_factor:.3f}x (computed from the source container duration / 18s). CUA and model-free replays use original saved capture pixels with transitions omitted, explicitly labeled. No generated touch or timestamp overlays.\n- Workbench screenshot: {'included at 18–28s, full-frame, separately hash-bound software capture; not native evidence' if workbench else 'not supplied; original recorded-Meta segment retained'}. No new inference or progress is depicted.
- Same FINAL-C export SHA-256 {summary['export_sha256']} binds the two saved model-free controls.\n- All copied source assets match full hashes in source-manifest.json. Identity aliases and allowlisted summary fields only. Aggregate numeric claims reference safe-aggregates.json and original-record/ledger-aggregate hashes; they are not producer-authenticated.\n- Rehearsal type: automated local decode metadata, pacing and frame extraction, not a fresh device/model run. Actual visual review remains parent-owned and pending.\n- Novice human readthrough: NOT DONE. Human script review and final private viewing remain pending.\n- B1 native baseline/fault testing: parent-owned; not claimed by this demo.\n- Producer/physical-tap/timestamp/OS attestation: NOT PROVIDED. No publication, submission or release approval.\n'''
 (out/'REHEARSAL.md').write_text(report)
 # Keep new generation products in --out only. Historical demo records stay unchanged.
 distribution_manifest(out,sources)
 return {'segments':len(entries),'seconds':180,'frames':4320,'sha256':sha(film),'peak_caption_cps':cps}
if __name__=='__main__':main()
