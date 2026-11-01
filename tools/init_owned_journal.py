#!/usr/bin/env python3
"""Initialize ONE fresh owned journal; preview by default. Never copy/reset history.

Trusted-local READY bootstrap metadata, not proof of historical absence or OS
attestation. No adb/device/model calls. Live replay still verifies actual ownership.
Use an exclusively owned, private runtime parent; adversarial writers are out of scope.
"""
from pathlib import Path
from hashlib import sha256
from contextlib import closing
import argparse
import json
import os
import sqlite3
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'examples'),str(ROOT)]
from reproloop.lab import read_owned_bootstrap,LAB_SETUP_SCHEMA
from reproloop.runtime.driver import RuntimeJournal
from reproloop.portable import real_directory,bounded_read
from tools.replay_owned_case import save,validate_journal_schema

BOOTSTRAP_MEMBERS={'bootstrap.json','avds','emulator-home','android-user','emulator.log','owner-marker.txt'}
MARKERS=('journal-init.lock','journal-init.intent.json','journal-init.complete.json')


def preflight(root,expected_avd,expected_serial,own_lock=False):
    root=real_directory(root)
    st=root.stat()
    if st.st_uid!=os.getuid()or st.st_mode&0o077:raise ValueError('private owner-only runtime root required')
    allowed=BOOTSTRAP_MEMBERS|({MARKERS[0]}if own_lock else set())
    if set(p.name for p in root.iterdir())-allowed:
        raise ValueError('existing journal/sidecar/init evidence or unexpected runtime member; reconcile, never replace')
    for child in root.iterdir():
        if child.is_symlink():raise ValueError('symlink runtime member forbidden')
    b=read_owned_bootstrap(root/'bootstrap.json')
    if(b['avd_name'],b['serial'])!=(expected_avd,expected_serial):raise ValueError('explicit owned target mismatch')
    avd=real_directory(Path(b['avd_dir']))
    if avd!=root/'avds'/(expected_avd+'.avd'):
        raise ValueError('AVD must belong to this exact runtime root; never shadow/copy another journal')
    for directory in('avds','emulator-home','android-user'):real_directory(root/directory)
    if bounded_read(root/'owner-marker.txt').decode().strip()!=b['owner_id']:raise ValueError('owner marker mismatch')
    return dict(schema=1,phase='PREVIEW',runtime_root=str(root),journal_path=str(root/'runtime.sqlite'),
                bootstrap_sha256=sha256(bounded_read(root/'bootstrap.json')).hexdigest(),
                identity={key:b[key]for key in('avd_name','serial','owner_id','avd_boot_id','config_sha256')},
                device_calls=0,model_calls=0,no_replace=True)


def initialize(root,expected_avd,expected_serial,execute=False):
    plan=preflight(root,expected_avd,expected_serial)
    if not execute:return plan
    root=real_directory(root);nonce=uuid.uuid4().hex
    # The gate is never deleted, including on failure. It is NOT the runtime lock.
    fd=os.open(root/MARKERS[0],os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb')as f:f.write(nonce.encode());f.flush();os.fsync(f.fileno())
    checked=preflight(root,expected_avd,expected_serial,own_lock=True)
    if checked!=plan:raise ValueError('bootstrap changed before exclusive initialization')
    started=dict(plan,phase='STARTED',nonce=nonce)
    save(root/MARKERS[1],started)
    fd=os.open(root/'runtime.sqlite',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    # No lease is created. Sentinel is not a claimed host boot identity.
    journal=RuntimeJournal(str(root/'runtime.sqlite'),'fresh-initializer-no-lease')
    with journal.locked()as db:db.execute(LAB_SETUP_SCHEMA)
    with closing(sqlite3.connect((root/'runtime.sqlite').as_uri()+'?mode=ro',uri=True))as db:
        validate_journal_schema(db)
        if any(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]for t in('lease','run_history','actions','lab_setup')):
            raise ValueError('fresh journal unexpectedly contains history')
    fd=os.open(root/'runtime.sqlite',os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    complete=dict(started,phase='COMPLETED',initial_journal_sha256=sha256((root/'runtime.sqlite').read_bytes()).hexdigest())
    save(root/MARKERS[2],complete)
    return complete


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-root',type=Path,required=True)
    p.add_argument('--expected-avd',required=True);p.add_argument('--expected-serial',required=True)
    p.add_argument('--execute-init',action='store_true')
    a=p.parse_args();os.umask(0o077)
    print(json.dumps(initialize(a.runtime_root,a.expected_avd,a.expected_serial,a.execute_init),indent=2))


if __name__=='__main__':main()
