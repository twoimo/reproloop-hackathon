"""Trusted owned-AVD app setup. Never expose this module as a model tool."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import json
import re
import uuid
import zipfile
from collections.abc import Mapping
from types import MappingProxyType
from .host import BoundedRunner, SystemClock
from .runtime.owned import OwnedTarget, OwnedAdbTransport, RuntimeStop, PACKAGE, name, number
from .runtime.driver import RuntimeDriver, RuntimeJournal
from .runtime.app_state import FixtureSpec, AppExpectation, AppStateReader


# Historical original builds: never overwrite these pins with a local rebuild.
KNOWN_APK_SHA256 = {
    'faulty': '5b7e27d291bf39e10b255c11b32abf6a2f56df89784c0136e5850277764233df',
    'fixed': '4bcd23747d32429c2c21fd4527bd9a481e6d11376b6b3b1fd27d424378cb3cb6',
}

LAB_SETUP_SCHEMA = 'CREATE TABLE IF NOT EXISTS lab_setup (id TEXT PRIMARY KEY,binding TEXT,payload TEXT,state TEXT,reason TEXT)'


def local_build_pins(pins):
    """An explicit trusted owner's declaration, not source/producer attestation."""
    if pins is None:
        return None
    if not isinstance(pins, Mapping) or set(pins) != {'faulty', 'fixed'}:
        raise ValueError('exact faulty/fixed local build pins required')
    values = dict(pins)
    if any(type(v) is not str or re.fullmatch(r'[0-9a-f]{64}', v) is None for v in values.values()):
        raise ValueError('lowercase SHA-256 local build pins required')
    if values['faulty'] == values['fixed']:
        raise ValueError('distinct faulty/fixed local build pins required')
    return MappingProxyType(values)


def checked_apk_sha256(apk, mode, admitted_apk_sha256=None):
    if mode not in ('faulty', 'fixed'):
        raise ValueError('build mode')
    pins = local_build_pins(admitted_apk_sha256)
    apk = Path(apk)
    if apk.is_symlink() or not apk.is_file() or apk.name != 'pockettasks-' + mode + '-debug.apk':
        raise RuntimeStop('known regular debug APK required')
    try:
        with zipfile.ZipFile(apk) as archive:
            if not {'AndroidManifest.xml', 'classes.dex'}.issubset(archive.namelist()):
                raise RuntimeStop('APK metadata missing')
    except zipfile.BadZipFile:
        raise RuntimeStop('APK ZIP metadata invalid') from None
    actual = sha256(apk.read_bytes()).hexdigest()
    expected = KNOWN_APK_SHA256 if pins is None else pins
    if actual != expected[mode]:
        raise RuntimeStop('APK differs from documented verified debug build' if pins is None
                          else 'APK differs from explicitly owner-admitted local build')
    return actual


def read_owned_bootstrap(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeStop('regular owned bootstrap required')
    b = json.loads(path.read_bytes())
    if not isinstance(b, dict) or b.get('phase') != 'READY' or not re.fullmatch(r'ReproLoop_[A-Za-z0-9_]{4,60}', b.get('avd_name', '')):
        raise RuntimeStop('foreign bootstrap')
    for key in ('owner_id', 'avd_boot_id'):
        name(b[key])
    if not re.fullmatch(r'emulator-[0-9]{4,6}', b.get('serial', '')) or type(b.get('pid')) is not int or b['pid'] <= 0:
        raise RuntimeStop('bootstrap identity')
    port = b.get('adb_server_port')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise RuntimeStop('bootstrap port')
    cfg = Path(b['avd_dir']) / 'config.ini'
    if cfg.is_symlink() or sha256(cfg.read_bytes()).hexdigest() != b['config_sha256']:
        raise RuntimeStop('AVD configuration changed')
    return b


@dataclass(frozen=True)
class LabConfig:
    bootstrap_path: Path
    adb_path: str
    faulty_apk: Path
    fixed_apk: Path
    journal_path: Path
    evidence_root: Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def save_blob(root, raw, suffix):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    key = sha256(raw).hexdigest(); dest = root / (key + suffix)
    try:
        with dest.open('xb') as out: out.write(raw)
    except FileExistsError:
        if dest.is_symlink() or sha256(dest.read_bytes()).hexdigest() != key:
            raise RuntimeStop('content address collision/corruption')
    return str(dest)


class EvidenceTransport(OwnedAdbTransport):
    def __init__(self, *args, evidence_root, **kwargs):
        super().__init__(*args, **kwargs)
        self.evidence_root = Path(evidence_root)
        self.observer = uuid.uuid4().hex
        self.last_frame = None
        self.evidencepaths = []

    def observe_capture_probe(self,png_before,xml,png_after,attempt,stable):
        record=super().observe_capture_probe(png_before,xml,png_after,attempt,stable)
        record.update(observer=self.observer,run_id=self.target.run_id,binding=self.target.binding,
                      capture_sequence_candidate=self.sequence+1)
        record['png_before_path']=save_blob(self.evidence_root,png_before,'.png')
        record['xml_path']=save_blob(self.evidence_root,xml,'.xml')
        record['png_after_path']=save_blob(self.evidence_root,png_after,'.png')
        meta=save_blob(self.evidence_root,canonical(record),'.stability.json')
        self.evidencepaths.extend((record['png_before_path'],record['xml_path'],record['png_after_path'],meta))
        return record

    def persist_capture(self, frame):
        if frame.binding != self.target.binding:
            raise RuntimeStop('foreign capture')
        png = save_blob(self.evidence_root, frame.png, '.png')
        xml = save_blob(self.evidence_root, frame.xml, '.xml')
        record = dict(frame.evidence(), observer=self.observer, run_id=self.target.run_id,
                      target=asdict(self.target), png_path=png, xml_path=xml,
                      stability_probes=getattr(self,'capture_probes',[]))
        meta = save_blob(self.evidence_root, canonical(record), '.capture.json')
        self.evidencepaths.extend((png, xml, meta))
        return record

    def capture(self, deadline):
        frame = super().capture(deadline)
        self.persist_capture(frame)
        self.last_frame = frame
        return frame

    def read_app_state(self, deadline):
        raw = super().read_app_state(deadline)
        self.evidencepaths.append(save_blob(self.evidence_root, raw, '.state.json'))
        return raw

    def read_app_events(self, deadline):
        raw = super().read_app_events(deadline)
        self.evidencepaths.append(save_blob(self.evidence_root, raw, '.events.jsonl'))
        return raw


@dataclass
class LabRun:
    target: OwnedTarget
    transport: EvidenceTransport
    driver: RuntimeDriver
    expectation: AppExpectation
    reset_observation: object
    reset_receipt: dict

    @property
    def last_frame(self): return self.transport.last_frame

    def persist_capture(self, frame): return self.transport.persist_capture(frame)


class OwnedLab:
    def __init__(self, config: LabConfig, runner=None, clock=None, *, host_boot_id=None,
                 admitted_apk_sha256=None):
        if type(config) is not LabConfig: raise ValueError('LabConfig required')
        # Caller obtains this through its read-only sysctl boundary, never shell here.
        if host_boot_id is None: raise ValueError('caller-injected host_boot_id required')
        self.config, self.runner, self.clock = config, runner or BoundedRunner(), clock or SystemClock()
        self.admitted_apk_sha256 = local_build_pins(admitted_apk_sha256)
        self.bootstrap = self._bootstrap()
        self.journal = RuntimeJournal(str(config.journal_path), name(host_boot_id))
        self.fixtures = {}
        self.register_fixture(FixtureSpec('DEV01', 0, 'A'))

    def register_fixture(self, fixture):
        if type(fixture) is not FixtureSpec: raise ValueError('typed fixture required')
        self.fixtures[fixture.sha256] = fixture

    def _bootstrap(self):
        return read_owned_bootstrap(self.config.bootstrap_path)

    def apk_sha256(self, mode):
        apk = self.config.faulty_apk if mode == 'faulty' else self.config.fixed_apk
        return checked_apk_sha256(apk, mode, self.admitted_apk_sha256)

    def _pin(self, transport, deadline):
        if self._bootstrap() != self.bootstrap: raise RuntimeStop('bootstrap changed')
        t = transport.target
        for args, wanted in ((('get-state',), 'device'), (('emu','avd','name'), t.avd_name+'\nOK'),
                             (('shell','cat','/proc/sys/kernel/random/boot_id'), t.boot_id),
                             (('shell','cat','/data/local/tmp/reproloop-owner'), t.owner_id)):
            if transport._cmd(args, deadline).decode().replace('\r\n','\n').strip() != wanted:
                raise RuntimeStop('setup owner/boot/AVD mismatch')

    def prepare(self, fixture, mode, run_id, generation, seconds=120):
        if type(fixture) is not FixtureSpec: raise ValueError('typed fixture required')
        name(run_id); number(seconds, .1, 120)
        if type(generation) is not int or not 1 <= generation <= 2147483647: raise ValueError('generation')
        # adb shell joins argv remotely. This MVP rejects all shell metacharacters/spaces.
        for value in (fixture.fixture_id, run_id, fixture.target_title, fixture.non_target_title):
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value): raise ValueError('non-shell-safe fixture')
        if fixture.target_title == 'Today': raise ValueError('non-discriminating fixture')
        self.register_fixture(fixture)
        apk = Path(self.config.faulty_apk if mode == 'faulty' else self.config.fixed_apk)
        apk_hash = self.apk_sha256(mode)
        b = self.bootstrap
        target = OwnedTarget(b['serial'], b['avd_name'], b['owner_id'], b['avd_boot_id'], apk_hash, run_id, generation)
        end = self.clock.monotonic() + seconds
        transport = EvidenceTransport(target, self.runner, self.clock, self.config.adb_path,
                                      b['adb_server_port'], evidence_root=self.config.evidence_root)
        driver = RuntimeDriver(transport, self.journal, self.clock, end)
        expected = AppExpectation(target, fixture, mode)
        with self.journal.locked() as db:
            db.execute(LAB_SETUP_SCHEMA)
            db.execute("UPDATE lab_setup SET state='UNKNOWN' WHERE state='PENDING'")
            db.execute("UPDATE actions SET state='UNKNOWN',reason='setup encountered pending' WHERE state='PENDING'")
            if db.execute("SELECT 1 FROM lab_setup WHERE state='UNKNOWN' UNION SELECT 1 FROM actions WHERE state='UNKNOWN'").fetchone():
                db.commit(); raise RuntimeStop('unknown intent requires reconciliation')
            row = db.execute('SELECT * FROM lease').fetchone()
            if row and row['host_boot'] == self.journal.host_boot_id and row['expires'] > self.clock.monotonic():
                raise RuntimeStop('live lease blocks setup')
            if db.execute('SELECT 1 FROM run_history WHERE generation>? OR (run_id=? AND generation=?)', (generation,run_id,generation)).fetchone():
                raise RuntimeStop('stale/reused run')
            self._pin(transport,end)
            if row: db.execute('UPDATE run_history SET retired=1 WHERE binding=?', (row['binding'],))
            db.execute('INSERT INTO run_history(binding,run_id,generation) VALUES(?,?,?)',(target.binding,run_id,generation))
            db.execute('INSERT OR REPLACE INTO lease VALUES(1,?,?,?,?,?,0)', (target.owner_id,self.journal.host_boot_id,target.binding,generation,end))
            commands = [('install','-r','-t',str(apk.absolute())), ('shell','pm','clear',PACKAGE),
                        ('shell','am','start','-W','-n',PACKAGE+'/.MainActivity','--ez','reset_fixture','true',
                         '--es','fixture_id',fixture.fixture_id,'--es','run_id',run_id,'--el','generation',str(generation),
                         '--ei','seed',str(fixture.seed),'--es','layout_variant',fixture.layout_variant,
                         '--es','target_title',fixture.target_title,'--es','non_target_title',fixture.non_target_title,
                         '--es','expected_fixture_sha256',fixture.sha256)]
            for index,args in enumerate(commands):
                self._pin(transport,end)
                if self.apk_sha256(mode) != apk_hash: raise RuntimeStop('APK bytes changed')
                identity = target.binding + ':' + str(index)
                db.execute('INSERT INTO lab_setup VALUES(?,?,?,?,?)',(identity,target.binding,json.dumps(args),'PENDING','intent committed'))
                db.commit(); db.execute('BEGIN IMMEDIATE')
                try:
                    driver._fence(db)
                    self._pin(transport,end)
                    output = transport._cmd(args,end,1_048_576)
                    if (index < 2 and b'Success' not in output) or (index == 2 and b'Error' in output):
                        raise RuntimeStop('setup acceptance unknown')
                except Exception as error:
                    db.execute("UPDATE lab_setup SET state='UNKNOWN',reason=? WHERE id=?",(type(error).__name__,identity))
                    db.commit(); raise
                db.execute("UPDATE lab_setup SET state='ACCEPTED',reason='bounded command accepted' WHERE id=?",(identity,))
            # Typed hidden readback precedes any claim of fixture preconditions.
            observation = AppStateReader(transport).collect(expected,end)
            snap = observation.snapshot
            if not observation.coherent or snap is None or snap.sequence != 1 or len(snap.events) != 1 or snap.events[0].action != 'fixture_loaded' or snap.cancel_order or (snap.target_title,snap.non_target_title) != (fixture.target_title,fixture.non_target_title):
                raise RuntimeStop('fresh reset readback required')
            driver._fence(db)
        receipt = dict(schema_version=1, target=asdict(target), fixture_sha256=fixture.sha256,
                       reset_log_sha256=snap.log_sha256, setup_method='install-r-t+pm-clear+explicit-reset',
                       host_boot_id=self.journal.host_boot_id, coherent=True, atomic=False)
        save_blob(self.config.evidence_root,canonical(receipt),'.reset.json')
        return LabRun(target,transport,driver,expected,observation,receipt)

    def finish(self, run):
        """Retire a completed run, not job cancellation. Never erase UNKNOWN."""
        if run.driver.journal is not self.journal: raise RuntimeStop('foreign lab run')
        with self.journal.locked() as db:
            if db.execute("SELECT 1 FROM actions WHERE state IN ('PENDING','UNKNOWN')").fetchone() or db.execute("SELECT 1 FROM lab_setup WHERE state IN ('PENDING','UNKNOWN')").fetchone():
                raise RuntimeStop('unresolved intent retains fence')
            row = db.execute('SELECT * FROM lease').fetchone()
            if not row or row['binding'] != run.target.binding or row['owner'] != run.target.owner_id or row['host_boot'] != self.journal.host_boot_id:
                raise RuntimeStop('foreign lease')
            db.execute('UPDATE run_history SET retired=1 WHERE binding=?',(run.target.binding,))
            db.execute('UPDATE lease SET expires=?,cancelled=1 WHERE singleton=1',(self.clock.monotonic(),))
