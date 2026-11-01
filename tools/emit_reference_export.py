#!/usr/bin/env python3
"""Emit a developer-authored B1 reference export, NOT video inference; no device/model."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'examples'),str(ROOT)]
from reproloop.reference import reference_export
from reproloop.portable import real_directory
from tools.replay_owned_case import save


def emit(case_id,faulty_sha,fixed_sha,out):
    export=reference_export(case_id,faulty_sha,fixed_sha)
    out=Path(out).absolute()
    real_directory(out.parent)
    if out.exists()or out.is_symlink():raise ValueError('exclusive new output required; no overwrite')
    save(out,export.to_bytes())
    return dict(case_id=case_id,export_sha256=export.digest(),bytes=len(export.to_bytes()),
                authorship='DEVELOPER_AUTHORED_B1_REFERENCE',model_calls=0,device_calls=0,
                not_video_inference=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for field in('case-id','faulty-sha','fixed-sha'):p.add_argument('--'+field,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();os.umask(0o077)
    print(json.dumps(emit(a.case_id,a.faulty_sha,a.fixed_sha,a.out),indent=2))


if __name__=='__main__':main()
