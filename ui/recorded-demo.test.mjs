import assert from 'node:assert/strict';
import test from 'node:test';
import {webcrypto} from 'node:crypto';
import {recordedAsset,recordedDocument,loadRecordedMedia,verifyRecordedBytes} from './recorded-demo.js';
import {loadCaseDocument} from './adapter.js';
if(!globalThis.crypto)globalThis.crypto=webcrypto;

test('bundled record preserves the actual distinct FINAL cohort and null scores',()=>{
 const loaded=loadCaseDocument(JSON.stringify(recordedDocument));assert.equal(loaded.ok,true,loaded.errors.join(' '));
 assert.equal(loaded.trust,'UNVERIFIED');assert.equal(loaded.document.cohort.split,'FINAL');assert.equal(loaded.document.cohort.valid_export_pairs,null);
});
test('only known case/slot/step catalog entries can initiate a media read',async()=>{
 let calls=0;const read=async()=>{calls++;throw Error('unexpected')};
 for(const [id,slot,step]of [['UNKNOWN','one',3],['FINAL-C','unknown',3],['FINAL-C','one',9],['constructor','one',3]])await assert.rejects(loadRecordedMedia(id,slot,step,read),/unavailable/);
 assert.equal(calls,0);
});
test('catalog distinguishes real intermediate frames from terminal image claims',()=>{
 assert.notEqual(recordedAsset('FINAL-C','one',0).sha256,recordedAsset('FINAL-C','one',3).sha256);
 assert.equal(recordedAsset('FINAL-C','one',0).sha256,recordedAsset('FINAL-C','two',0).sha256);
 assert.equal(recordedAsset('FINAL-A','one',0).sha256,recordedAsset('FINAL-A','one',3).sha256);
});
test('static reads omit credentials and reject redirects',async()=>{
 await assert.rejects(loadRecordedMedia('FINAL-C','one',3,async(url,options)=>{
  assert.match(url,/recorded\/FINAL-C-faulty-step-4.png$/);assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');
  return {ok:true,redirected:true};
 }),/not included/);
});
test('incorrect size or hash cannot become a displayed recorded file',async()=>{
 await assert.rejects(loadRecordedMedia('FINAL-C','one',3,async()=>({ok:true,redirected:false,arrayBuffer:async()=>new ArrayBuffer(1)})),/size mismatch/);
 const n=recordedAsset('FINAL-C','one',3).bytes;
 await assert.rejects(loadRecordedMedia('FINAL-C','one',3,async()=>({ok:true,redirected:false,arrayBuffer:async()=>new ArrayBuffer(n)})),/hash mismatch/);
});
test('byte verification returns a file only for exact known bytes and type',async()=>{
 const bytes=new Uint8Array([1,2,3,4]).buffer;
 const asset={path:'recorded/synthetic-test.png',bytes:4,sha256:'9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',type:'image/png'};
 const result=await verifyRecordedBytes(asset,bytes);assert.equal(result.file.size,4);assert.equal(result.expectedHash,asset.sha256);
 await assert.rejects(verifyRecordedBytes({...asset,type:'text/html'},bytes),/type mismatch/);
});
