#!/usr/bin/env python3
"""Package the PRIVATE recorded viewer. No execution, upload or publication."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import tempfile
import zipfile

FILES = ('ui/index.html','ui/console.css','ui/app.js','ui/adapter.js','ui/recorded-demo.js',
         'ui/fixtures/synthetic-illustration.json','ui/fixtures/recorded-case.json','ui/fixtures/recorded-assets.json')


def regular(path):
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise ValueError('regular nonsymlink input required')
    if path.stat().st_size > 8000000:
        raise ValueError('input size limit')
    return path.read_bytes()


def build(root, media, out):
    root, media, out = Path(root).absolute(), Path(media).absolute(), Path(out).absolute()
    if out.exists() or out.is_symlink() or out.parent.resolve() != out.parent:
        raise ValueError('new output in a real directory required')
    if not out.parent.is_dir():
        raise ValueError('output parent must already exist')
    payload = {n.removeprefix('ui/'):regular(root/n) for n in FILES}
    payload['LICENSE'] = regular(root/'LICENSE')
    payload['licenses/Hallmark-LICENSE'] = regular(root/'third_party/hallmark/LICENSE')
    catalog = json.loads(payload['fixtures/recorded-assets.json'])
    records=[]
    for case in catalog.values():
        records.extend(case[k] for k in ('one','two','video'))
        for step in case.get('steps',[]):records.extend(step[k] for k in ('one','two'))
    for asset in records:
        name=asset['path']
        if not re.fullmatch(r'recorded/[A-Za-z0-9][A-Za-z0-9._-]*\.(png|mp4)',name):
            raise ValueError('invalid catalog path')
        raw=regular(media/Path(name).name)
        if len(raw)!=asset['bytes'] or hashlib.sha256(raw).hexdigest()!=asset['sha256']:
            raise ValueError('recorded media bytes do not match catalog')
        if name in payload and payload[name]!=raw:raise ValueError('conflicting asset')
        payload[name]=raw
    payload['PRIVATE_VIEWER_README.txt']=b'''PRIVATE RECORDED VIEWER. NOT A PUBLIC RELEASE.
Serve this extracted folder over loopback, for example:
python3 -m http.server 8000 --bind 127.0.0.1
Open the printed local address and choose Explore recorded run.
This is existing recorded evidence, not a new Meta/device run or a backend verdict.
FINAL3/3 is one family with correlated variants, separate from original pilot2/5.
The fixed control is developer supplied with AI assistance, not generated repair.
Duplicate pixels are not independent visual corroboration. No host/OS attestation.
Project-owned code: root LICENSE (MIT). Hallmark notice: licenses/.
Media/binary/organizer rights, public release and contest submission remain held.
'''
    if sum(map(len,payload.values()))>32000000:raise ValueError('package size limit')
    manifest={'kind':'PRIVATE_RECORDED_PRODUCT_VIEWER','public_release_approved':False,
              'new_Meta_or_native_calls':0,'evidence_trust':'UNVERIFIED',
              'files':[{'path':n,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}for n,raw in sorted(payload.items())]}
    payload['viewer-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    fd,stage=tempfile.mkstemp(prefix='.workbench-',suffix='.partial',dir=out.parent)
    try:
        with os.fdopen(fd,'wb')as stream:
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED)as z:
                for name,raw in sorted(payload.items()):
                    info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.external_attr=0o100600<<16
                    z.writestr(info,raw,compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(stage)as z:
            if {n:z.read(n)for n in z.namelist()}!=payload:raise ValueError('archive verification failed')
        os.link(stage,out)
    finally:
        os.unlink(stage)
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--media-dir',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    try:m=build(a.source,a.media_dir,a.out)
    except(OSError,ValueError,KeyError,TypeError):p.exit(2,'private viewer packaging refused; inspect inputs/output\n')
    print(f"PRIVATE recorded viewer:{len(m['files'])} payload files; no release or new run")


if __name__=='__main__':main()
