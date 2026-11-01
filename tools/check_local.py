#!/usr/bin/env python3
"""Run existing local synthetic/boundary suites, never native/API evaluation."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def python_suites(root):
    """Tests are intentionally non-package directories; root discovery runs zero."""
    suites = {file.parent for file in (root/'tests').rglob('test*.py') if file.is_file()}
    for name in ('examples', 'review_tools'):
        path = root/name
        if any(path.glob('test*.py')):
            suites.add(path)
    return sorted(suites)


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11+ is required')
    env = os.environ.copy()
    paths = [str(ROOT/'src'), str(ROOT/'examples'), str(ROOT)]
    if env.get('PYTHONPATH'):
        paths.append(env['PYTHONPATH'])
    env['PYTHONPATH'] = os.pathsep.join(paths)
    suites = python_suites(ROOT)
    if not suites:
        raise SystemExit('No Python suites discovered; no checks were completed')
    total = 0
    for suite in suites:
        print(f'Checking {suite.relative_to(ROOT)}', flush=True)
        result = subprocess.run([sys.executable,'-m','unittest','discover','-s',str(suite),'-q'],
            cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        print(result.stdout, end='', flush=True)
        count = re.search(r'Ran (\d+) tests?', result.stdout)
        if result.returncode or count is None or int(count.group(1)) == 0:
            return result.returncode or 1
        total += int(count.group(1))
    node = shutil.which('node')
    if node is None:
        raise SystemExit('Node is missing; UI checks are blocked, not silently skipped')
    # Hyphenated standalone unittest file is not found by directory discovery.
    bundle_tests = ROOT/'ui/scripts/test-build-host-bundle.py'
    if not bundle_tests.is_file():
        raise SystemExit('Console producer checks are missing; validation is blocked')
    result = subprocess.run([sys.executable,str(bundle_tests),'-q'],cwd=ROOT,env=env,
        text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
    print(result.stdout,end='',flush=True)
    count = re.search(r'Ran (\d+) tests?',result.stdout)
    if result.returncode or count is None or int(count.group(1)) == 0:
        return result.returncode or 1
    total += int(count.group(1))
    result = subprocess.run([node,'--test','ui/adapter.test.mjs','ui/dom.test.mjs','ui/recorded-demo.test.mjs'],cwd=ROOT,timeout=60)
    print(f'Python tests run: {total}. UI exit: {result.returncode}. Native/API checks were NOT run.',flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
