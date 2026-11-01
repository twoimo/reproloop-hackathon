import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { webcrypto } from 'node:crypto';
import vm from 'node:vm';
import test from 'node:test';
import * as adapter from './adapter.js';
const source=readFileSync(new URL('./app.js',import.meta.url),'utf8');
const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');
const sample=JSON.parse(readFileSync(new URL('./fixtures/synthetic-illustration.json',import.meta.url),'utf8'));
class Element {
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.textContent='';this.hidden=false;}
 get firstChild(){return this.children[0]||null;}
 append(...nodes){this.children.push(...nodes);}
 removeChild(node){this.children.splice(this.children.indexOf(node),1);}
 addEventListener(name,fn){this.listeners[name]=fn;}
 setAttribute(k,v){this.attributes[k]=v;}
 getAttribute(k){return this.attributes[k]??null;}
 removeAttribute(k){delete this.attributes[k];}
 focus(){this.focused=true;}
 pause(){this.paused=true;}
}
function boot(){
 const nodes=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
 const buttons=['intake','cases','evidence','demo'].map(name=>{const e=new Element('button');e.attributes['data-view']=name;return e;});
 const document={getElementById:id=>nodes.get(id)||null,createElement:tag=>new Element(tag),
 querySelectorAll:selector=>selector==='[data-view]'?buttons:[],
 querySelector:selector=>selector.startsWith('[data-view=')?buttons.find(e=>selector===`[data-view="${e.attributes['data-view']}"]`):new Element('h2')};
 let count=0;const revoked=[];
 const context={...adapter,sampleText:sample,recordedDocument:JSON.parse(readFileSync(new URL("./fixtures/recorded-case.json",import.meta.url),"utf8")),loadRecordedMedia:async()=>{throw Error("not included in test")},document,crypto:webcrypto,URL:{createObjectURL:()=>`blob:local-${++count}`,revokeObjectURL:x=>revoked.push(x)},console};
 vm.createContext(context);vm.runInContext(source.replace(/^import .*\n/gm,''),context);
 return{nodes,buttons,context,revoked};
}
test('browser module parses and boots against actual HTML id contract',()=>{
 execFileSync(process.execPath,['--check',new URL('./app.js',import.meta.url).pathname]);
 const app=boot();assert.equal(app.nodes.get('page-title').textContent,'No real cases loaded');
 app.buttons[2].listeners.click();assert.equal(app.nodes.get('view-evidence').hidden,false);
});
test('local JSON reaches evidence without dead event handlers',async()=>{
 const app=boot();await app.nodes.get('file').listeners.change({target:{files:[{size:1000,text:async()=>JSON.stringify(sample)}]}});
 assert.equal(app.nodes.get('view-evidence').hidden,false);assert.equal(app.nodes.get('trust-line').textContent.includes('unverified'),true);
});
test('two image slots do not replace one another and clear revokes both',async()=>{
 const app=boot();const file={size:4,type:'image/png',name:'local.png',arrayBuffer:async()=>new Uint8Array([1,2,3,4]).buffer};
 await vm.runInContext('attachSlot("one", testFile, "image")',vm.createContext({...app.context,testFile:file}));
 await vm.runInContext('attachSlot("two", testFile, "image")',vm.createContext({...app.context,testFile:file}));
 assert.equal(app.nodes.get('preview-stage-one').children.length,1);assert.equal(app.nodes.get('preview-stage-two').children.length,1);
 app.nodes.get('clear-preview').listeners.click();assert.equal(app.nodes.get('preview-stage-one').children.length,0);assert.equal(app.nodes.get('preview-stage-two').children.length,0);assert.equal(app.revoked.length,2);
});

async function twoCaseDocument(app) {
 const document=JSON.parse(JSON.stringify(sample));
 document.mode='real';document.evidence_level='HOST_OBSERVED';document.illustration=null;
 document.pilot={planned_case_ids:['P01','P02','P03','P04','P05'],attempted:2,complete:2,unknown:0,excluded:0,not_run_ids:['P03','P04','P05'],valid_export_pairs:null,fixed_failure_signals:null,invalid_confirmations:null};
 document.cases=[{case_id:'P01',file_claim:{verdict:'SUCCESS'}},{case_id:'P02',file_claim:{verdict:'KNOWN_FAILED'}}];
 await app.nodes.get('file').listeners.change({target:{files:[{size:1000,text:async()=>JSON.stringify(document)}]}});
}
function mediaFile(name='local.png',type='image/png') {
 return {size:4,type,name,arrayBuffer:async()=>new Uint8Array([1,2,3,4]).buffer};
}
async function attachForTest(app,slot,file) {
 app.context.testFile=file;
 return vm.runInContext(`attachSlot("${slot}",testFile,"${slot==='video'?'video':'image'}")`,app.context);
}
test('case selection clears all old-case previews and file inputs',async()=>{
 const app=boot();await twoCaseDocument(app);
 for(const slot of ['one','two','video'])await attachForTest(app,slot,mediaFile(slot,slot==='video'?'video/mp4':'image/png'));
 app.nodes.get('case-select').listeners.change({target:{value:'P02'}});
 for(const slot of ['one','two','video']){
  assert.equal(app.nodes.get('preview-stage-'+slot).children.length,0);
  assert.match(app.nodes.get('preview-line-'+slot).textContent,/No local/);
 }
 for(const id of ['image-file','image-file-two','video-file'])assert.equal(app.nodes.get(id).value,'');
 assert.equal(app.revoked.length,3);
 assert.equal(app.nodes.get('case-select').value,'P02');
});
test('case-list navigation also clears an old image',async()=>{
 const app=boot();await twoCaseDocument(app);await attachForTest(app,'one',mediaFile());
 app.nodes.get('case-list').children[1].children[0].listeners.click();
 assert.equal(app.nodes.get('case-select').value,'P02');
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.revoked.length,1);
});
test('selecting the same case retains its own media',async()=>{
 const app=boot();await twoCaseDocument(app);await attachForTest(app,'one',mediaFile());
 app.nodes.get('case-select').listeners.change({target:{value:'P01'}});
 assert.equal(app.nodes.get('preview-stage-one').children.length,1);
 assert.equal(app.revoked.length,0);
});
test('a pending old-case digest cannot write a new-case hash claim',async()=>{
 const app=boot();await twoCaseDocument(app);let finish;
 const file={...mediaFile('old-case.png'),arrayBuffer:()=>new Promise(resolve=>{finish=resolve})};
 const pending=attachForTest(app,'one',file);
 assert.equal(app.nodes.get('preview-stage-one').children.length,1);
 app.nodes.get('case-select').listeners.change({target:{value:'P02'}});
 finish(new Uint8Array([1,2,3,4]).buffer);await pending;
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.match(app.nodes.get('preview-line-one').textContent,/No local image/);
 assert.doesNotMatch(app.nodes.get('preview-line-one').textContent,/old-case|SHA-256|match/);
});

function finalCohortDocument() {
 const doc=JSON.parse(JSON.stringify(sample));doc.schema='reproloop.evidence.v2';doc.mode='real';doc.evidence_level='HOST_OBSERVED';doc.illustration=null;
 doc.cohort={...doc.pilot,id:'native-v4obs1-final',split:'FINAL',condition:'B3_NATIVE_VIDEO_SAMPLED_CONTEXT_V4_OBS1',planned_case_ids:['FINAL-A','FINAL-B','FINAL-C'],attempted:3,complete:3,unknown:0,excluded:0,not_run_ids:[]};
 delete doc.pilot;doc.cases=doc.cohort.planned_case_ids.map(case_id=>({case_id,file_claim:{verdict:'SUCCESS'}}));return doc;
}
function loadDocumentForTest(app,document) {
 return app.nodes.get('file').listeners.change({target:{files:[{size:1000,text:async()=>JSON.stringify(document)}]}});
}
test('FINAL context shows three planned cases without a backend score',async()=>{
 const app=boot();await loadDocumentForTest(app,finalCohortDocument());
 assert.match(app.nodes.get('cohort-line').textContent,/native-v4obs1-final \/ FINAL/);
 assert.equal(app.nodes.get('planned').textContent,'FINAL-A, FINAL-B, FINAL-C');
 assert.equal(app.nodes.get('attempted').textContent,'3');
 assert.equal(app.nodes.get('not-run').textContent,'0');
 assert.equal(app.nodes.get('pairs').textContent,'not recorded');
 assert.match(app.nodes.get('trust-line').textContent,/unverified/);
 assert.match(app.nodes.get('evidence-body').children.flatMap(e=>e.children.map(p=>p.textContent)).join(' '),/FINAL case, unverified file claim/);
});
test('switching cohort documents clears even same-id previews and old hash work',async()=>{
 const app=boot();const doc=finalCohortDocument();await loadDocumentForTest(app,doc);
 await attachForTest(app,'one',mediaFile());
 doc.cohort.id='different-cohort';doc.cohort.condition='different-condition';
 await loadDocumentForTest(app,doc);
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.revoked.length,1);
 assert.match(app.nodes.get('cohort-line').textContent,/different-cohort/);
});
test('invalid document clears old images and no evidence row stays active',async()=>{
 const app=boot();await loadDocumentForTest(app,finalCohortDocument());await attachForTest(app,'one',mediaFile());
 await app.nodes.get('file').listeners.change({target:{files:[{size:100,text:async()=>'{'}]}});
 app.buttons[2].listeners.click();
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.nodes.get('case-select').value,'');
 assert.match(app.nodes.get('evidence-body').children[0].textContent,/No evidence row/);
});
test('latest file selection wins over a slower old document read',async()=>{
 const app=boot();let finish;
 const old=app.nodes.get('file').listeners.change({target:{files:[{size:1000,text:()=>new Promise(resolve=>{finish=resolve})}]}});
 await loadDocumentForTest(app,finalCohortDocument());
 finish(JSON.stringify(sample));await old;
 assert.match(app.nodes.get('cohort-line').textContent,/native-v4obs1-final/);
 assert.equal(app.nodes.get('planned').textContent,'FINAL-A, FINAL-B, FINAL-C');
});
test('clear cancels a pending document without silently restoring it',async()=>{
 const app=boot();let finish;
 const pending=app.nodes.get('file').listeners.change({target:{files:[{size:1000,text:()=>new Promise(resolve=>{finish=resolve})}]}});
 app.nodes.get('clear').listeners.click();finish(JSON.stringify(finalCohortDocument()));await pending;
 assert.equal(app.nodes.get('page-title').textContent,'No real cases loaded');
 assert.equal(app.nodes.get('attempted').textContent,'0');
});
test('oversized or unreadable replacement cannot retain prior evidence',async()=>{
 for(const file of [{size:200001,text:async()=>''},{size:10,text:async()=>{throw Error('read failed')}}]){
  const app=boot();await loadDocumentForTest(app,finalCohortDocument());await attachForTest(app,'one',mediaFile());
  await app.nodes.get('file').listeners.change({target:{files:[file]}});
  assert.equal(app.nodes.get('preview-stage-one').children.length,0);
  assert.equal(app.nodes.get('view-intake').hidden,false);
  assert.equal(app.nodes.get('errors').children.length,1);
 }
});

test('malformed models leave a coherent inactive state and valid import recovers',async()=>{
 const app=boot();const bad=finalCohortDocument();bad.cases[0].models=[null];
 await loadDocumentForTest(app,bad);
 assert.equal(app.nodes.get('view-intake').hidden,false);
 assert.match(app.nodes.get('cohort-line').textContent,/No active cohort/);
 assert.equal(app.nodes.get('attempted').textContent,'not recorded');
 assert.match(app.nodes.get('errors').children.map(e=>e.textContent).join(' '),/models/);
 await loadDocumentForTest(app,finalCohortDocument());
 assert.equal(app.nodes.get('view-evidence').hidden,false);
 assert.match(app.nodes.get('cohort-line').textContent,/native-v4obs1-final/);
});
test('unexpected synchronous display failure becomes a coherent import error',async()=>{
 const app=boot();const create=app.context.document.createElement;let fail=true;let contentRead=false;
 app.context.document.createElement=tag=>{if(contentRead&&fail){fail=false;throw Error('display fault')}return create(tag)};
 await app.nodes.get('file').listeners.change({target:{files:[{size:1000,text:async()=>{contentRead=true;return JSON.stringify(finalCohortDocument())}}]}});
 assert.equal(app.nodes.get('view-intake').hidden,false);
 assert.match(app.nodes.get('errors').children.map(e=>e.textContent).join(' '),/could not be displayed/);
 assert.match(app.nodes.get('cohort-line').textContent,/No active cohort/);
 await loadDocumentForTest(app,finalCohortDocument());
 assert.equal(app.nodes.get('view-evidence').hidden,false);
});

test('non-scoring recorded row compares both image and video hashes without scoring',async()=>{
 const app=boot(),doc=structuredClone(sample);
 const bytes=new Uint8Array([1,2,3,4]);
 const digest=Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
 doc.mode='real';doc.evidence_level='HOST_OBSERVED';
 doc.illustration.png_claims={faulty:digest,fixed:'0'.repeat(64)};
 doc.illustration.media={sha256:digest,label:'Recorded local file'};
 await loadDocumentForTest(app,doc);
 await attachForTest(app,'one',mediaFile());
 assert.match(app.nodes.get('preview-line-one').textContent,/Bytes match the imported claim/);
 await attachForTest(app,'two',mediaFile());
 assert.match(app.nodes.get('preview-line-two').textContent,/Bytes DO NOT match the imported claim/);
 await attachForTest(app,'video',mediaFile('local.mp4','video/mp4'));
 assert.match(app.nodes.get('preview-line-video').textContent,/Bytes match the imported claim/);
 assert.equal(app.nodes.get('attempted').textContent,'0');
 assert.equal(app.nodes.get('pairs').textContent,'not recorded');
 assert.match(app.nodes.get('trust-line').textContent,/unverified/);
});

test('invalid media replacement clears only its old slot and revokes its URL',async()=>{
 for(const bad of [{...mediaFile('wrong.txt','text/plain')},{...mediaFile('huge.png'),size:8000001},mediaFile('wrong.mp4','video/mp4')]){
  const app=boot();await twoCaseDocument(app);
  await attachForTest(app,'one',mediaFile());await attachForTest(app,'two',mediaFile());
  await attachForTest(app,'one',bad);
  assert.equal(app.nodes.get('preview-stage-one').children.length,0);
  assert.equal(app.nodes.get('preview-stage-two').children.length,1);
  assert.equal(app.revoked.length,1);
  assert.doesNotMatch(app.nodes.get('preview-line-one').textContent,/SHA-256|Bytes match/);
  assert.equal(app.nodes.get('case-select').value,'P01');
 }
});
test('pending old digest cannot overwrite an invalid replacement error',async()=>{
 const app=boot();await twoCaseDocument(app);let finish;
 const old={...mediaFile('old.png'),arrayBuffer:()=>new Promise(resolve=>{finish=resolve})};
 const pending=attachForTest(app,'one',old);
 await attachForTest(app,'one',mediaFile('invalid.txt','text/plain'));
 const error=app.nodes.get('preview-line-one').textContent;
 finish(new Uint8Array([1,2,3,4]).buffer);await pending;
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.nodes.get('preview-line-one').textContent,error);
 assert.doesNotMatch(error,/old.png|SHA-256/);
});
test('invalid video replacement pauses and removes the old video',async()=>{
 const app=boot();await twoCaseDocument(app);
 await attachForTest(app,'video',mediaFile('old.mp4','video/mp4'));
 const old=app.nodes.get('preview-stage-video').children[0];
 await attachForTest(app,'video',mediaFile('wrong.png','image/png'));
 assert.equal(old.paused,true);assert.equal(app.nodes.get('preview-stage-video').children.length,0);
 assert.equal(app.revoked.length,1);
});

function stubRecordedFile(caseId,slot) {
 return {file:mediaFile(caseId+'-'+slot+(slot==='video'?'.mp4':'.png'),slot==='video'?'video/mp4':'image/png'),expectedHash:'9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a'};
}
test('recorded example selects actual cohort but never computes a backend score',async()=>{
 const app=boot();app.context.loadRecordedMedia=async(caseId,slot)=>stubRecordedFile(caseId,slot);
 assert.equal(app.nodes.get('recorded-demo').disabled,false);
 await app.nodes.get('recorded-demo').listeners.click();
 assert.equal(app.nodes.get('case-select').value,'FINAL-C');
 assert.match(app.nodes.get('walkthrough-step-label').textContent,/Saved step 4 of 4/);
 assert.equal(app.nodes.get('action-list').children.length,4);
 assert.equal(app.nodes.get('pairs').textContent,'not recorded');
 assert.match(app.nodes.get('trust-line').textContent,/unverified/);
 assert.match(app.nodes.get('preview-line-one').textContent,/Bytes match the saved-frame claim/);
 await app.nodes.get('step-prev').listeners.click();
 assert.match(app.nodes.get('walkthrough-step-label').textContent,/Saved step 3 of 4/);
 assert.match(app.nodes.get('compare-note').textContent,/Intermediate saved states only/);
 assert.equal(app.nodes.get('attempted').textContent,'3');
 const video=app.nodes.get('preview-stage-video').children[0];
 assert.equal(video.muted,true);assert.equal(video.volume,0);
});
test('clear cancels pending trusted recorded reads without restoring old media',async()=>{
 const app=boot(),reads=[];app.context.loadRecordedMedia=(id,slot)=>new Promise(resolve=>reads.push(()=>resolve(stubRecordedFile(id,slot))));
 const pending=app.nodes.get('recorded-demo').listeners.click();
 app.nodes.get('clear').listeners.click();reads.forEach(done=>done());await pending;
 assert.equal(app.nodes.get('page-title').textContent,'No real cases loaded');
 for(const slot of ['one','two','video'])assert.equal(app.nodes.get('preview-stage-'+slot).children.length,0);
});
test('a local document wins over an older recorded media load and triggers no catalog reads',async()=>{
 const app=boot(),reads=[];app.context.loadRecordedMedia=(id,slot)=>new Promise(resolve=>reads.push(()=>resolve(stubRecordedFile(id,slot))));
 const pending=app.nodes.get('recorded-demo').listeners.click();
 const local=finalCohortDocument();local.cohort.id='local-independent-file';
 await loadDocumentForTest(app,local);const count=reads.length;reads.forEach(done=>done());await pending;
 assert.match(app.nodes.get('cohort-line').textContent,/local-independent-file/);
 assert.equal(reads.length,count);assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.nodes.get('step-prev').disabled,true);
});
test('missing recorded assets remain explicit and do not substitute synthetic success',async()=>{
 const app=boot();await app.nodes.get('recorded-demo').listeners.click();
 assert.match(app.nodes.get('preview-line-one').textContent,/Saved media unavailable/);
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.nodes.get('pairs').textContent,'not recorded');
 assert.match(app.nodes.get('trust-line').textContent,/unverified/);
});

test('recorded case-list navigation loads the newly selected case media',async()=>{
 const app=boot(),calls=[];app.context.loadRecordedMedia=async(id,slot)=>{calls.push(id);return stubRecordedFile(id,slot)};
 await app.nodes.get('recorded-demo').listeners.click();calls.length=0;
 await app.nodes.get('case-list').children[0].children[0].listeners.click();
 assert.equal(app.nodes.get('case-select').value,'FINAL-A');assert.equal(calls.length,3);
 assert.ok(calls.every(id=>id==='FINAL-A'));assert.match(app.nodes.get('preview-line-one').textContent,/FINAL-A/);
});
test('same-case terminal reset cannot leave an intermediate image after failed reads',async()=>{
 const app=boot();app.context.loadRecordedMedia=async(id,slot)=>stubRecordedFile(id,slot);
 await app.nodes.get('recorded-demo').listeners.click();await app.nodes.get('step-prev').listeners.click();
 app.context.loadRecordedMedia=async()=>{throw Error('missing')};
 await app.nodes.get('case-select').listeners.change({target:{value:'FINAL-C'}});
 assert.match(app.nodes.get('walkthrough-step-label').textContent,/step 4 of 4/);
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);assert.match(app.nodes.get('preview-line-one').textContent,/unavailable/);
});
test('a changed case rejects late previous-case bundled media',async()=>{
 const app=boot(),reads=[];app.context.loadRecordedMedia=(id,slot)=>id==='FINAL-C'?new Promise(resolve=>reads.push(()=>resolve(stubRecordedFile(id,slot)))):Promise.resolve(stubRecordedFile(id,slot));
 const pending=app.nodes.get('recorded-demo').listeners.click();
 await app.nodes.get('case-select').listeners.change({target:{value:'FINAL-A'}});reads.forEach(done=>done());await pending;
 assert.equal(app.nodes.get('case-select').value,'FINAL-A');assert.match(app.nodes.get('preview-line-one').textContent,/FINAL-A/);assert.doesNotMatch(app.nodes.get('preview-line-one').textContent,/FINAL-C/);
});
test('a changed saved step rejects late terminal-frame bundled reads',async()=>{
 const app=boot(),reads=[];app.context.loadRecordedMedia=(id,slot,step)=>step===3?new Promise(resolve=>reads.push(()=>resolve(stubRecordedFile('old-terminal',slot)))):Promise.resolve(stubRecordedFile('new-intermediate',slot));
 const pending=app.nodes.get('recorded-demo').listeners.click();await app.nodes.get('step-prev').listeners.click();reads.forEach(done=>done());await pending;
 assert.match(app.nodes.get('walkthrough-step-label').textContent,/step 3 of 4/);assert.match(app.nodes.get('preview-line-one').textContent,/new-intermediate/);assert.doesNotMatch(app.nodes.get('preview-line-one').textContent,/old-terminal/);
});
test('manual file selection supersedes pending bundled reads and clears obsolete loading copy',async()=>{
 const app=boot(),reads=[];app.context.loadRecordedMedia=(id,slot)=>new Promise(resolve=>reads.push(()=>resolve(stubRecordedFile('old-bundled',slot))));
 const pending=app.nodes.get('recorded-demo').listeners.click();
 app.nodes.get('image-file').listeners.change({target:{files:[mediaFile('manual.png')]}});
 await new Promise(resolve=>setImmediate(resolve));reads.forEach(done=>done());await pending;
 assert.match(app.nodes.get('preview-line-one').textContent,/manual.png/);assert.doesNotMatch(app.nodes.get('preview-line-one').textContent,/old-bundled/);assert.doesNotMatch(app.nodes.get('preview-line-two').textContent,/Loading/);
});
test('manual replacement preserves ready other slots while the first bundled hash is pending',async()=>{
 const app=boot();let finish;app.context.loadRecordedMedia=async(id,slot)=>slot==='one'?{file:{...mediaFile('old-hash.png'),arrayBuffer:()=>new Promise(resolve=>{finish=resolve})},expectedHash:'0'.repeat(64)}:stubRecordedFile(id,slot);
 const pending=app.nodes.get('recorded-demo').listeners.click();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(typeof finish,'function');app.nodes.get('image-file').listeners.change({target:{files:[mediaFile('manual-after-hash.png')]}});
 await new Promise(resolve=>setImmediate(resolve));finish(new Uint8Array([1,2,3,4]).buffer);await pending;
 assert.match(app.nodes.get('preview-line-one').textContent,/manual-after-hash.png/);assert.doesNotMatch(app.nodes.get('preview-line-one').textContent,/old-hash/);assert.equal(app.nodes.get('preview-stage-two').children.length,1);
});


test('same recorded case-list selection preserves manual file, URL and pending hash ownership',async()=>{
 const app=boot();app.context.loadRecordedMedia=async(id,slot)=>stubRecordedFile(id,slot);
 await app.nodes.get('recorded-demo').listeners.click();let finish;
 const file={...mediaFile('manual-final-c.png'),arrayBuffer:()=>new Promise(resolve=>{finish=resolve})};
 const pendingManual=app.nodes.get('image-file').listeners.change({target:{files:[file]}});
 const url=vm.runInContext('state.previewUrls.one',app.context);
 await app.nodes.get('case-list').children[2].children[0].listeners.click();
 assert.equal(app.nodes.get('preview-stage-one').children[0].alt,'manual-final-c.png');
 assert.equal(vm.runInContext('state.previewUrls.one',app.context),url);assert.equal(app.revoked.includes(url),false);
 finish(new Uint8Array([1,2,3,4]).buffer);await pendingManual;
 assert.match(app.nodes.get('preview-line-one').textContent,/manual-final-c.png SHA-256/);
 assert.equal(app.nodes.get('pairs').textContent,'not recorded');
});

test('unresolved recorded video never withholds ready control images',async()=>{
 const app=boot();let finishVideo;
 app.context.loadRecordedMedia=(id,slot)=>slot==='video'?new Promise(resolve=>{finishVideo=()=>resolve(stubRecordedFile(id,slot))}):Promise.resolve(stubRecordedFile(id,slot));
 const pending=app.nodes.get('recorded-demo').listeners.click();await new Promise(resolve=>setImmediate(resolve));
 const ready=['one','two','video'].map(slot=>app.nodes.get('preview-stage-'+slot).children.length);
 const line=app.nodes.get('preview-line-one').textContent;
 finishVideo();await pending;
 assert.deepEqual(ready,[1,1,0]);assert.match(line,/FINAL-C-one/);assert.equal(app.nodes.get('preview-stage-video').children.length,1);
});

test('explicit No case row survives rendering and never fetches a fallback case',async()=>{
 const app=boot();const calls=[];app.context.loadRecordedMedia=async(id,slot)=>{calls.push(id);return stubRecordedFile(id,slot)};
 await app.nodes.get('recorded-demo').listeners.click();calls.length=0;
 await app.nodes.get('case-select').listeners.change({target:{value:''}});app.buttons[2].listeners.click();
 assert.equal(app.nodes.get('case-select').value,'');assert.equal(vm.runInContext('state.caseId',app.context),null);
 assert.deepEqual(calls,[]);assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.nodes.get('walkthrough-step-label').textContent,'No case row is selected.');assert.match(app.nodes.get('compare-note').textContent,/Choose a case/);
 assert.equal(app.nodes.get('evidence-body').children[0].textContent,'No evidence row is selected.');
});

test('same-case bundled retry cannot apply an older failed request over newer ready media',async()=>{
 const app=boot(),rejects=[];app.context.loadRecordedMedia=()=>new Promise((resolve,reject)=>rejects.push(reject));
 const older=app.nodes.get('recorded-demo').listeners.click();app.context.loadRecordedMedia=async(id,slot)=>stubRecordedFile('newer-'+id,slot);
 await app.nodes.get('case-list').children[2].children[0].listeners.click();rejects.forEach(reject=>reject(Error('older failed')));await older;
 assert.match(app.nodes.get('preview-line-one').textContent,/newer-FINAL-C/);assert.doesNotMatch(app.nodes.get('preview-line-one').textContent,/unavailable/);
});

test('No case row cancels late recorded media without replacing the empty selection',async()=>{
 const app=boot(),reads=[];app.context.loadRecordedMedia=(id,slot)=>new Promise(resolve=>reads.push(()=>resolve(stubRecordedFile(id,slot))));
 const pending=app.nodes.get('recorded-demo').listeners.click();await app.nodes.get('case-select').listeners.change({target:{value:''}});
 reads.forEach(done=>done());await pending;assert.equal(app.nodes.get('case-select').value,'');
 for(const slot of ['one','two','video'])assert.equal(app.nodes.get('preview-stage-'+slot).children.length,0);
});

test('JSON input resets immediately after File capture, including read failure and clear',async()=>{
 const app=boot();const input=app.nodes.get('file');let finish;
 input.value='same-file.json';input.files=[{size:20,text:()=>new Promise((resolve,reject)=>{finish=reject})}];
 const pending=input.listeners.change({target:input});assert.equal(input.value,'');finish(Error('read failed'));await pending;
 assert.match(app.nodes.get('errors').children[0].textContent,/could not be read/);
 input.value='same-file.json';input.files=[{size:1000,text:async()=>JSON.stringify(sample)}];await input.listeners.change({target:input});assert.equal(input.value,'');
 app.nodes.get('clear').listeners.click();assert.equal(input.value,'');
 input.value='same-file.json';await input.listeners.change({target:input});assert.equal(input.value,'');assert.equal(app.nodes.get('view-evidence').hidden,false);
});

test('synthetic nonzero file counts are not described as zero or real executions',async()=>{
 const app=boot(),doc=JSON.parse(JSON.stringify(sample));doc.meta_calls=1;doc.pilot.attempted=1;doc.pilot.complete=1;doc.pilot.not_run_ids=doc.pilot.not_run_ids.slice(1);
 await loadDocumentForTest(app,doc);assert.equal(app.nodes.get('attempted').textContent,'1');assert.match(app.nodes.get('calls').textContent,/1 meta/);
 assert.match(app.nodes.get('page-lead').textContent,/Counts are file claims, not real executions/);assert.doesNotMatch(app.nodes.get('page-lead').textContent,/stay at zero/);
 assert.match(app.nodes.get('trust-line').textContent,/unverified/);assert.equal(app.nodes.get('pairs').textContent,'not recorded');
});

test('a non-F01 local import has neutral comparison claims and invokes no recorded loader',async()=>{
 const app=boot();let reads=0;app.context.loadRecordedMedia=async()=>{reads++;throw Error('must not be called')};
 const doc=finalCohortDocument();doc.cases[0].bug_family='Different local family';doc.source='recorded-demo';
 await loadDocumentForTest(app,doc);assert.equal(reads,0);assert.equal(app.nodes.get('comparison-heading').textContent,'Inspect the selected case.');
 assert.equal(app.nodes.get('comparison-expectation').textContent,'Task and oracle text are file claims.');assert.doesNotMatch(app.nodes.get('comparison-family').textContent,/F01/);
});


test('manual image does not cancel another slot pending on the network',async()=>{
 const app=boot();let finishVideo;
 app.context.loadRecordedMedia=(id,slot)=>slot==='video'?new Promise(resolve=>{finishVideo=()=>resolve(stubRecordedFile(id,slot))}):Promise.resolve(stubRecordedFile(id,slot));
 const loading=app.nodes.get('recorded-demo').listeners.click();
 await app.nodes.get('image-file').listeners.change({target:{files:[mediaFile('manual-during-video.png')],value:'same.png'}});
 finishVideo();await loading;
 assert.equal(app.nodes.get('preview-stage-one').children[0].alt,'manual-during-video.png');
 assert.equal(app.nodes.get('preview-stage-two').children.length,1);
 assert.equal(app.nodes.get('preview-stage-video').children.length,1);
 assert.match(app.nodes.get('preview-line-video').textContent,/FINAL-C-video/);
});

test('rejected manual media cancels only its own old read and permits an explicit retry',async()=>{
 const app=boot(),reads=[];app.context.loadRecordedMedia=(id,slot)=>new Promise(resolve=>reads.push(()=>resolve(stubRecordedFile(id,slot))));
 const loading=app.nodes.get('recorded-demo').listeners.click();
 await app.nodes.get('image-file').listeners.change({target:{files:[{...mediaFile('too-large.png'),size:8000001}],value:'same.png'}});
 const error=app.nodes.get('preview-line-one').textContent;
 reads.forEach(done=>done());await loading;
 assert.equal(app.nodes.get('preview-stage-one').children.length,0);
 assert.equal(app.nodes.get('preview-line-one').textContent,error);
 assert.equal(app.nodes.get('preview-stage-two').children.length,1);
 assert.equal(app.nodes.get('preview-stage-video').children.length,1);
 app.context.loadRecordedMedia=async(id,slot)=>stubRecordedFile(id,slot);
 await app.nodes.get('case-list').children[2].children[0].listeners.click();
 assert.equal(app.nodes.get('preview-stage-one').children.length,1);
});

test('all manual media inputs reset after valid and rejected selections',async()=>{
 for(const [id,type]of [['image-file','image/png'],['image-file-two','image/png'],['video-file','video/mp4']]){
  const app=boot();await twoCaseDocument(app);const input=app.nodes.get(id);
  input.value='same-file';input.files=[{...mediaFile('rejected','text/plain')}];
  await input.listeners.change({target:input});assert.equal(input.value,'');
  input.value='same-file';input.files=[mediaFile('valid',type)];
  await input.listeners.change({target:input});assert.equal(input.value,'');
 }
});

test('manual intermediate image comparison names the terminal claim, not the selected step',async()=>{
 const app=boot();app.context.loadRecordedMedia=async(id,slot)=>stubRecordedFile(id,slot);
 await app.nodes.get('recorded-demo').listeners.click();await app.nodes.get('step-prev').listeners.click();
 await app.nodes.get('image-file').listeners.change({target:{files:[mediaFile('saved-intermediate.png')],value:'same.png'}});
 assert.match(app.nodes.get('preview-line-one').textContent,/imported terminal-control claim \(not the selected saved step\)/);
 assert.match(app.nodes.get('trust-line').textContent,/unverified/);
 assert.equal(app.nodes.get('pairs').textContent,'not recorded');
});


for (const slot of ['one', 'two', 'video']) {
 for (const outcome of ['digest success', 'read failure']) {
  test(`same-case retry failure survives an older ${slot} ${outcome}`, async () => {
   const app=boot();let resolveOld,rejectOld;
   app.context.loadRecordedMedia=async(id,requestedSlot)=>requestedSlot===slot
    ? {file:{...mediaFile('older-'+slot,slot==='video'?'video/mp4':'image/png'),arrayBuffer:()=>new Promise((resolve,reject)=>{resolveOld=resolve;rejectOld=reject})},expectedHash:'0'.repeat(64)}
    : stubRecordedFile(id,requestedSlot);
   const older=app.nodes.get('recorded-demo').listeners.click();
   await new Promise(resolve=>setImmediate(resolve));
   assert.equal(typeof resolveOld,'function');
   const cachedUrl=vm.runInContext(`state.previewUrls.${slot}`,app.context);
   app.context.loadRecordedMedia=async()=>{throw Error('newer fetch unavailable')};
   await app.nodes.get('case-list').children[2].children[0].listeners.click();
   const failureLine=app.nodes.get('preview-line-'+slot).textContent;
   assert.match(failureLine,/Saved media unavailable/);
   if(outcome==='digest success')resolveOld(new Uint8Array([1,2,3,4]).buffer);
   else rejectOld(Error('older file read failed'));
   await older;
   assert.equal(app.nodes.get('preview-line-'+slot).textContent,failureLine);
   assert.equal(vm.runInContext(`state.previewUrls.${slot}`,app.context),cachedUrl);
   assert.equal(app.revoked.includes(cachedUrl),false);
   assert.equal(app.nodes.get('pairs').textContent,'not recorded');
   assert.match(app.nodes.get('trust-line').textContent,/unverified/);
  });
 }
}
