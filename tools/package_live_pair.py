#!/usr/bin/env python3
"""Read-only private saved-pair packaging/verification; no native or model calls."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'examples'), str(ROOT)]
from reproloop.portable import package, verify, LIMITS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--case-root', help='exact saved case directory')
    modes.add_argument('--verify', help='private archive to verify offline')
    parser.add_argument('--out', help='new absolute .zip path for packaging')
    parser.add_argument('--extract-to', help='new absolute directory for verification')
    args = parser.parse_args()
    if args.case_root:
        if not args.out or args.extract_to: parser.error('packaging requires --out only')
        report = package(args.case_root, args.out)
    else:
        if not args.extract_to or args.out: parser.error('verification requires --extract-to only')
        report = verify(args.verify, args.extract_to)
    print(json.dumps(dict(valid=report.valid, verdict=report.collected_pair.decision.verdict,
                         files_checked=report.proof['files_checked'], bytes_checked=report.proof['bytes_checked'],
                         limits=LIMITS), indent=2))


if __name__ == '__main__':
    main()
