"""Local serialized executor: committed intent, then fenced OS call, then readback."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, asdict
import fcntl
import json
import sqlite3
from .owned import OwnedAdbTransport, RuntimeStop, Frame, name, number


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    request_id: str
    kind: str
    preframe_hash: str
    resource_id: str = ''
    text: str = ''
    wait_seconds: float = 0
    x: int | None = None
    y: int | None = None

    def __post_init__(self):
        from .owned import digest
        name(self.action_id); name(self.request_id); digest(self.preframe_hash)
        if self.kind not in ('tap', 'wait', 'screenshot'):
            raise ValueError('unsupported action')
        if type(self.resource_id) is not str or type(self.text) is not str or len(self.resource_id) > 256 or len(self.text) > 4096:
            raise ValueError('unbounded selector')
        if (self.x is None) != (self.y is None) or any(v is not None and (type(v)is not int or not 0<=v<16384) for v in (self.x,self.y)) or (self.kind!='tap' and self.x is not None):
            raise ValueError('paired bounded native click coordinates required')
        number(self.wait_seconds, 0, 2)
        if self.kind != 'wait' and self.wait_seconds != 0:
            raise ValueError('unexpected wait')


@dataclass(frozen=True)
class ActionReceipt:
    action_id: str
    state: str
    reason: str
    evidence: dict | None = None


class RuntimeJournal:
    def __init__(self, path: str, host_boot_id: str):
        self.path = str(path)
        self.host_boot_id = name(host_boot_id)
        with self.locked() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS lease (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner TEXT NOT NULL,
              host_boot TEXT NOT NULL, binding TEXT NOT NULL, generation INTEGER NOT NULL,
              expires REAL NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS run_history (
              binding TEXT PRIMARY KEY, run_id TEXT, generation INTEGER NOT NULL,
              cancelled INTEGER NOT NULL DEFAULT 0, retired INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS run_history_generation ON run_history(generation);
            CREATE INDEX IF NOT EXISTS run_history_identity ON run_history(run_id,generation);
            CREATE TABLE IF NOT EXISTS actions (
              action_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
              payload TEXT NOT NULL, owner TEXT NOT NULL, binding TEXT NOT NULL,
              generation INTEGER NOT NULL, preframe TEXT NOT NULL, planned_args TEXT NOT NULL,
              state TEXT NOT NULL, reason TEXT NOT NULL, evidence TEXT);
            ''')
            # Upgrade the surviving legacy lease without inventing lost history.
            # Legacy cancel increments the lease generation; retain its original.
            db.execute('''INSERT OR IGNORE INTO run_history
                SELECT binding,NULL,generation-cancelled,cancelled,0 FROM lease''')

    @contextmanager
    def locked(self):
        # Separate file descriptions serialize threads AND cooperating processes.
        # Never unlink lock file. All journal mutation paths use this same lock.
        with open(self.path + '.lock','a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            db = sqlite3.connect(self.path, timeout=0.25, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                yield db
                if db.in_transaction:
                    db.commit()
            finally:
                db.close()
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def receipt(row):
        return ActionReceipt(row['action_id'],row['state'],row['reason'],json.loads(row['evidence']) if row['evidence'] else None)

    def get(self, action_id):
        with self.locked() as db:
            row = db.execute('SELECT * FROM actions WHERE action_id=?',(action_id,)).fetchone()
            return self.receipt(row) if row else None


class RuntimeDriver:
    def __init__(self, transport: OwnedAdbTransport, journal: RuntimeJournal, clock,
                 deadline: float, max_actions: int = 24):
        number(deadline,0,1e15)
        if type(max_actions) is not int or not 1 <= max_actions <= 24:
            raise ValueError('invalid cap')
        self.transport, self.journal, self.clock = transport,journal,clock
        self.deadline, self.max_actions = deadline,max_actions
        self.target = transport.target

    def _fence(self, db, reserve=0):
        row = db.execute('SELECT * FROM lease').fetchone()
        t = self.target
        now = self.clock.monotonic()
        if not row or (row['owner'],row['host_boot'],row['binding'],row['generation'],row['cancelled']) != (t.owner_id,self.journal.host_boot_id,t.binding,t.generation,0):
            raise RuntimeStop('ownership/stale/cancelled fence')
        if min(row['expires'],self.deadline) - now <= reserve:
            raise RuntimeStop('deadline/lease reservation')
        return min(row['expires'],self.deadline)

    def _capture(self, db):
        frame = self.transport.capture(self._fence(db))
        self._fence(db)  # includes CPU parsing and the last command's completion
        return frame

    def start(self, lease_seconds=30):
        number(lease_seconds,0.1,120)
        self.transport.discover(self.deadline)
        with self.journal.locked() as db:
            row = db.execute('SELECT * FROM lease').fetchone()
            # Crash residue is UNKNOWN, never eligible for re-dispatch.
            db.execute("UPDATE actions SET state='UNKNOWN',reason='restart pending intent' WHERE state='PENDING'")
            if db.execute("SELECT 1 FROM actions WHERE state='UNKNOWN'").fetchone():
                db.commit()  # preserve crash classification even though start is blocked
                raise RuntimeStop('unknown action requires reconciliation')
            t = self.target
            if db.execute('SELECT 1 FROM run_history WHERE generation>? LIMIT 1',(t.generation,)).fetchone():
                raise RuntimeStop('superseded generation')
            if db.execute('''SELECT 1 FROM run_history
                WHERE (binding=? OR (run_id=? AND generation=?))
                  AND (cancelled=1 OR retired=1 OR binding<>?) LIMIT 1''',
                (t.binding,t.run_id,t.generation,t.binding)).fetchone():
                raise RuntimeStop('cancelled/retired run cannot restart')
            if self.clock.monotonic() >= self.deadline:
                raise RuntimeStop('deadline')
            if row:
                same = (row['owner'],row['host_boot'],row['binding']) == (self.target.owner_id,self.journal.host_boot_id,self.target.binding)
                live = row['host_boot'] == self.journal.host_boot_id and row['expires'] > self.clock.monotonic()
                if live and not same:
                    raise RuntimeStop('another owner lease')
                if same and row['cancelled']:
                    raise RuntimeStop('cancelled generation cannot restart')
            if row and row['binding'] != t.binding:
                db.execute('UPDATE run_history SET retired=1 WHERE binding=?',(row['binding'],))
            db.execute('''INSERT INTO run_history(binding,run_id,generation) VALUES(?,?,?)
                ON CONFLICT(binding) DO UPDATE SET run_id=excluded.run_id''',
                (t.binding,t.run_id,t.generation))
            db.execute('INSERT OR REPLACE INTO lease VALUES(1,?,?,?,?,?,0)',
                       (self.target.owner_id,self.journal.host_boot_id,self.target.binding,self.target.generation,
                        min(self.deadline,self.clock.monotonic()+lease_seconds)))

    def cancel(self):
        # Waits behind in-flight command/readback. Cannot revoke accepted OS input.
        with self.journal.locked() as db:
            self._fence(db)
            db.execute('UPDATE run_history SET cancelled=1 WHERE binding=?',(self.target.binding,))
            db.execute('UPDATE lease SET cancelled=1,generation=generation+1 WHERE singleton=1')

    def capture(self):
        with self.journal.locked() as db:
            return self._capture(db)

    def collect_app_state(self, expectation):
        """Collect trusted app evidence under the same executor serialization."""
        from .app_state import AppStateReader
        with self.journal.locked() as db:
            self._fence(db)
            lease = db.execute('SELECT expires FROM lease').fetchone()[0]
            observation = AppStateReader(self.transport).collect(expectation,min(self.deadline,lease))
            self._fence(db)
            return observation

    def execute(self, request: ActionRequest, frame: Frame, expected):
        if type(request) is not ActionRequest or type(frame) is not Frame or not callable(expected):
            raise ValueError('typed request/frame and trusted readback predicate required')
        payload = json.dumps(asdict(request),sort_keys=True)
        with self.journal.locked() as db:
            prior = db.execute('SELECT * FROM actions WHERE action_id=? OR request_id=?',(request.action_id,request.request_id)).fetchone()
            if prior:
                if prior['payload'] != payload or prior['binding'] != self.target.binding:
                    raise RuntimeStop('duplicate identity conflict')
                return self.journal.receipt(prior)
            self._fence(db, 0.05)
            if db.execute("SELECT 1 FROM actions WHERE state IN ('PENDING','UNKNOWN')").fetchone():
                raise RuntimeStop('unresolved intent blocks dependent action')
            count = db.execute('SELECT count(*) FROM actions WHERE binding=?',(self.target.binding,)).fetchone()[0]
            if count >= self.max_actions:
                raise RuntimeStop('action cap')
            if request.preframe_hash != frame.evidence_sha256 or frame.binding != self.target.binding:
                raise RuntimeStop('preframe mismatch')
            current = self._capture(db)
            if current.png != frame.png or current.xml != frame.xml:
                raise RuntimeStop('stale screen/hierarchy')
            coords = current.resolve(request.resource_id,request.text,request.x,request.y) if request.kind == 'tap' else None
            args = ('shell','input','tap',str(coords[0]),str(coords[1])) if coords else (request.kind,str(request.wait_seconds))
            # Reserve minimum readback slack, and clip every command to lease+deadline.
            reserve = request.wait_seconds + 0.05
            self._fence(db,reserve)
            db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (request.action_id,request.request_id,payload,self.target.owner_id,self.target.binding,
                 self.target.generation,frame.evidence_sha256,json.dumps(args),'PENDING','intent committed',None))
            db.commit()  # durable BEFORE any OS input
            db.execute('BEGIN IMMEDIATE')
            self._fence(db,reserve)  # lock retained across commit; no cooperating cancel gap
            lease = db.execute('SELECT expires FROM lease').fetchone()[0]
            end = min(self.deadline,lease)
            try:
                if request.kind == 'tap':
                    self.transport.tap(*coords,current,end)
                elif request.kind == 'wait':
                    self.clock.sleep(request.wait_seconds)
                after = self._capture(db)
                accepted = expected(after)
                self._fence(db)
                if type(accepted) is not bool:
                    raise RuntimeStop('readback predicate must return bool')
                state = 'ACCEPTED' if accepted else 'NOT_ACCEPTED'
                reason, evidence = 'fresh readback predicate',after.evidence()
            except Exception as error:
                state,reason,evidence = 'UNKNOWN',type(error).__name__,None
            db.execute('UPDATE actions SET state=?,reason=?,evidence=? WHERE action_id=?',
                       (state,reason,json.dumps(evidence) if evidence else None,request.action_id))
            return ActionReceipt(request.action_id,state,reason,evidence)

    def reconcile(self, action_id, expected):
        """Read-only recapture of same intent; false remains UNKNOWN, never retry."""
        with self.journal.locked() as db:
            row = db.execute('SELECT * FROM actions WHERE action_id=?',(action_id,)).fetchone()
            if not row or row['binding'] != self.target.binding or row['state'] not in ('PENDING','UNKNOWN'):
                raise RuntimeStop('no matching unresolved intent')
            lease = db.execute('SELECT * FROM lease').fetchone()
            if not lease or (lease['owner'],lease['host_boot'],lease['binding']) != (self.target.owner_id,self.journal.host_boot_id,self.target.binding):
                raise RuntimeStop('reconciliation owner mismatch')
            self.transport.discover(self.deadline)
            after = self.transport.capture(self.deadline)
            accepted = expected(after)
            if self.clock.monotonic() >= self.deadline:
                raise RuntimeStop('reconciliation deadline')
            if type(accepted) is not bool:
                raise ValueError('typed predicate required')
            state = 'ACCEPTED' if accepted else 'UNKNOWN'
            db.execute('UPDATE actions SET state=?,reason=?,evidence=? WHERE action_id=?',
                       (state,'read-only reconciliation',json.dumps(after.evidence()),action_id))
            return ActionReceipt(action_id,state,'read-only reconciliation',after.evidence())
