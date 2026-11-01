#!/usr/bin/env python3
"""Replay one canonical export on the explicitly pinned owned AVD; no model/HTTP/key."""
from pathlib import Path
from hashlib import sha256
from contextlib import closing
import argparse
import dataclasses
import json
import os
import platform
import re
import sqlite3
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'examples'),str(ROOT)]
from evaluation.splits import build_frozen_splits_v2,get_native_scenario
from reproloop.portable import bounded_read,export_from_bytes,real_directory
from reproloop.pair_binding import bind_saved_pair,strict_json
from reproloop.lab import LabConfig,OwnedLab,checked_apk_sha256,local_build_pins,read_owned_bootstrap
from reproloop.replay import model_free_replay
from repro_oracle import Verdict


def save(path,value):
    raw=value if isinstance(value,bytes)else(json.dumps(value,indent=2)+'\n').encode()
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


# Persisted v1 layout: column order matters to existing positional INSERTs.
JOURNAL_SCHEMA = {
    'actions': [('action_id','TEXT',0,None,1),('request_id','TEXT',1,None,0),('payload','TEXT',1,None,0),('owner','TEXT',1,None,0),('binding','TEXT',1,None,0),('generation','INTEGER',1,None,0),('preframe','TEXT',1,None,0),('planned_args','TEXT',1,None,0),('state','TEXT',1,None,0),('reason','TEXT',1,None,0),('evidence','TEXT',0,None,0)],
    'lab_setup': [('id','TEXT',0,None,1),('binding','TEXT',0,None,0),('payload','TEXT',0,None,0),('state','TEXT',0,None,0),('reason','TEXT',0,None,0)],
    'run_history': [('binding','TEXT',0,None,1),('run_id','TEXT',0,None,0),('generation','INTEGER',1,None,0),('cancelled','INTEGER',1,'0',0),('retired','INTEGER',1,'0',0)],
    'lease': [('singleton','INTEGER',0,None,1),('owner','TEXT',1,None,0),('host_boot','TEXT',1,None,0),('binding','TEXT',1,None,0),('generation','INTEGER',1,None,0),('expires','REAL',1,None,0),('cancelled','INTEGER',1,'0',0)],
}


def validate_journal_schema(db):
    if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
        raise ValueError('corrupt journal requires read-only reconciliation')
    for table,expected in JOURNAL_SCHEMA.items():
        rows=db.execute('PRAGMA table_info('+table+')').fetchall()
        actual=[(row[1],row[2].upper(),row[3],row[4],row[5])for row in rows]
        if actual!=expected:
            raise ValueError('incomplete/incompatible journal schema requires read-only reconciliation; never invent empty history')
    unique_request=False
    for index in db.execute('PRAGMA index_list(actions)').fetchall():
        quoted='"'+index[1].replace('"','""')+'"'
        if index[2]and not index[4]and [row[2]for row in db.execute('PRAGMA index_info('+quoted+')')]==['request_id']:
            unique_request=True
    lease_sql=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='lease'").fetchone()[0]
    if not unique_request or not re.search(r'CHECK\s*\(\s*singleton\s*=\s*1\s*\)',lease_sql,re.I):
        raise ValueError('incompatible journal schema constraints require read-only reconciliation')


def runtime_state(root):
    root=real_directory(root)
    initialized=False
    # Initializer receipts are additive. Original private journals predate them.
    markers=[root/name for name in ('journal-init.lock','journal-init.intent.json','journal-init.complete.json')]
    if any(p.exists()or p.is_symlink()for p in markers):
        if not all(p.is_file()and not p.is_symlink()for p in markers):
            raise ValueError('incomplete journal initialization requires read-only reconciliation')
        intent=strict_json(bounded_read(markers[1]));done=strict_json(bounded_read(markers[2]))
        boot_hash=sha256(bounded_read(root/'bootstrap.json')).hexdigest()
        if (intent.get('phase')!='STARTED'or done.get('phase')!='COMPLETED'
            or intent.get('nonce')!=done.get('nonce')
            or any(v.get('runtime_root')!=str(root)or v.get('journal_path')!=str(root/'runtime.sqlite')for v in(intent,done))
            or bounded_read(markers[0]).decode()!=intent.get('nonce')
            or any(v.get('bootstrap_sha256')!=boot_hash for v in(intent,done))):
            raise ValueError('incomplete/changed journal initialization requires read-only reconciliation')
        initialized=True
    journal=root/'runtime.sqlite'
    if not journal.is_file()or journal.is_symlink():raise ValueError('existing owned journal required; use explicit fresh initializer only for a new owned root; never copy/reset history')
    try:
        with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True,timeout=1))as db:
            validate_journal_schema(db)
            pending=any(db.execute('SELECT 1 FROM '+table+" WHERE state IN ('PENDING','UNKNOWN') LIMIT 1").fetchone()for table in('actions','lab_setup'))
            if db.execute("SELECT 1 FROM run_history WHERE generation IS NULL OR typeof(generation)!='integer' OR generation<1 LIMIT 1").fetchone():
                raise ValueError('invalid journal generation requires read-only reconciliation')
            generation=db.execute('SELECT MAX(generation) FROM run_history').fetchone()[0]
            generation=0 if generation is None else generation
            if generation==0 and not initialized:raise ValueError('empty unmarked journal requires explicit fresh initialization; never infer empty history')
            leases=db.execute('SELECT expires,cancelled FROM lease').fetchall()
            if len(leases)>1:raise ValueError('ambiguous lease requires read-only reconciliation')
            lease=leases[0]if leases else None
    except sqlite3.Error:
        raise ValueError('incompatible/corrupt journal requires read-only reconciliation')from None
    if type(generation)is not int or not 0<=generation<2147483647:raise ValueError('journal generation exhausted/invalid')
    if pending or(lease and not lease[1]and lease[0]>time.monotonic()):raise ValueError('original pending/unknown/live lease requires read-only reconciliation')
    return generation+1


def admitted_pins(args):
    values=getattr(args,'admit_local_build',None)
    if values is None:return None
    if len(values)!=2:raise ValueError('two explicitly admitted local build hashes required')
    return local_build_pins(dict(zip(('faulty','fixed'),values)))


def prepare(args):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}',args.run_id):raise ValueError('safe stable run id required')
    if not re.fullmatch(r'[0-9a-f]{40}',args.source_revision):raise ValueError('declared source revision required; not source attestation')
    root=real_directory(args.runtime_root)
    boot=read_owned_bootstrap(root/'bootstrap.json')
    if boot.get('phase')!='READY'or boot.get('avd_name')!=args.expected_avd or boot.get('serial')!=args.expected_serial:raise ValueError('explicit owned bootstrap target mismatch')
    generation=runtime_state(root)
    export=export_from_bytes(bounded_read(args.export))
    scenario=get_native_scenario(args.case_id)
    real_directory(args.apk_root)
    pins=admitted_pins(args)
    hashes={mode:checked_apk_sha256(args.apk_root/('pockettasks-'+mode+'-debug.apk'),mode,pins)for mode in('faulty','fixed')}
    spec=scenario.to_case_spec(hashes['faulty'],hashes['fixed'])
    if(export.package,export.task_sha256,export.fixture_sha256)!=(scenario.package_name,spec.task_sha256,spec.fixture_sha256):raise ValueError('export case/fixture/package mismatch')
    expected=[('task_target','Target task: '+scenario.target_title,'tasks'),('rename_open','Rename','selected'),('preset_today','Today','rename'),('cancel_edit','Cancel','rename')]
    if [(step.resource_id,step.visible_text,step.expected_screen)for step in export.steps]!=[(scenario.package_name+':id/'+rid,text,screen)for rid,text,screen in expected]:raise ValueError('explicit four-step F01 export required')
    return dict(apk_admission='ORIGINAL_PIN'if pins is None else'LOCAL_BUILD_OWNER_ADMITTED',admitted_build_sha256=None if pins is None else dict(pins),lab_sha256=sha256((ROOT/'src/reproloop/lab.py').read_bytes()).hexdigest(),source_commit=args.source_revision,case_id=scenario.case_id,manifest_sha256=build_frozen_splits_v2().manifest_sha256,run_id=args.run_id,generation=generation,export_sha256=export.digest(),build_sha256=hashes,model_calls=0,device_action='NONE until explicit --execute-owned',limits=['same explicit owned bootstrap and existing journal, no replacement','no model, HTTP, Meta ledger or key dependency','fresh source directory does not mean a fresh machine or different AVD']),scenario,export,spec


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in('runtime-root','apk-root','export','out'):parser.add_argument('--'+name,type=Path,required=True)
    for name in('case-id','run-id','expected-avd','expected-serial','source-revision'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--execute-owned',action='store_true')
    parser.add_argument('--admit-local-build',nargs=2,metavar=('FAULTY_SHA','FIXED_SHA'),help='explicit trusted-owner local debug builds; not source attestation')
    parser.add_argument('--adb',type=Path,default=Path.home()/'Library/Android/sdk/platform-tools/adb')
    args=parser.parse_args();os.umask(0o077)
    plan,scenario,export,spec=prepare(args)
    if args.out.exists()or args.out.is_symlink():raise ValueError('new output required; reconcile existing intent instead of replay')
    real_directory(args.out.parent)
    if not args.execute_owned:print(json.dumps(plan,indent=2));return 0
    if platform.system()!='Darwin'or platform.machine()not in('arm64','aarch64'):raise ValueError('native replay currently supports macOS ARM64 only')
    if args.adb.is_symlink()or not args.adb.is_file()or not os.access(args.adb,os.X_OK):raise ValueError('installed regular executable --adb required')
    host=sha256(subprocess.check_output(['/usr/sbin/sysctl','-n','kern.boottime'])).hexdigest()
    args.out.mkdir(mode=0o700);(args.out/'evidence').mkdir();(args.out/'model').mkdir()
    plan['runner_sha256']=sha256(Path(__file__).read_bytes()).hexdigest()
    save(args.out/'intent.json',plan);save(args.out/'model/semantic-export.json',export.to_bytes())
    config=LabConfig(args.runtime_root/'bootstrap.json',str(args.adb),args.apk_root/'pockettasks-faulty-debug.apk',args.apk_root/'pockettasks-fixed-debug.apk',args.runtime_root/'runtime.sqlite',args.out/'evidence')
    lab=OwnedLab(config,host_boot_id=host,admitted_apk_sha256=admitted_pins(args));fixture=scenario.to_fixture_spec();lab.register_fixture(fixture)
    results=[];start=time.monotonic()
    for mode in('faulty','fixed'):
        result=model_free_replay(lab,export,spec,mode,args.run_id+'-'+mode,plan['generation'],120)
        save(args.out/(mode+'-replay.json'),dataclasses.asdict(result));results.append(result)
        print(json.dumps(dict(mode=mode,complete=result.complete,model_calls=result.model_calls,reason=result.reason)),flush=True)
        if not result.complete:break
    summary=dict(case_id=scenario.case_id,generation=plan['generation'],complete_pair=False,model_calls=sum(r.model_calls for r in results),completed_runs=sum(r.complete for r in results),planned_runs=2,wall_seconds=time.monotonic()-start,status='INCOMPLETE_NO_RETRY')
    if len(results)==2 and all(r.complete for r in results):
        report=bind_saved_pair(spec,export,fixture,args.out/'faulty-replay.json',args.out/'fixed-replay.json',args.out/'evidence',plan['generation'])
        summary.update(complete_pair=report.valid and report.collected_pair.decision.verdict is Verdict.CONFIRMED,verdict=report.collected_pair.decision.verdict if report.collected_pair else None,files_checked=report.proof.get('files_checked'),bytes_checked=report.proof.get('bytes_checked'))
        if summary['complete_pair']:summary['status']='CONFIRMED'
    save(args.out/'summary.json',summary);print(json.dumps(summary,indent=2),flush=True)
    return 0 if summary['complete_pair']else 2


if __name__=='__main__':raise SystemExit(main())
