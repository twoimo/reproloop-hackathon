"""Trusted read-only app evidence; never a model tool or standalone verdict."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from .owned import OwnedTarget, PACKAGE, RuntimeStop, name, digest

ACTIONS = frozenset(('fixture_loaded','task_open','rename_open','select_preset','cancel_edit','save_edit','dismiss_edit'))
META = frozenset(('schema_version','package','build_mode','fixture_id','fixture_sha256','seed','layout_variant','run_id','generation'))
STATE = META | {'fixture','target_id','target_title','non_target_id','non_target_title','sequence','cancel_count','cancel_order','created_at_unix_ms','updated_at_unix_ms','last_action'}
EVENT = META | {'sequence','timestamp_unix_ms','action','task_id','before_title','draft_title','after_title','cancel_count','target_title','non_target_title'}

class AppEvidenceError(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


def require(ok, reason):
    if not ok: raise AppEvidenceError(reason)


def integer(value, low=0, high=2**63-1):
    return type(value) is int and low <= value <= high


def title(value, empty=False):
    return type(value) is str and (0 if empty else 1) <= len(value) <= 64 and value == value.strip() and all(32 <= ord(c) <= 126 for c in value)


def pairs(items):
    result = {}
    for key,value in items:
        require(key not in result,'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def parse(raw, maximum):
    require(type(raw) is bytes and 0 < len(raw) <= maximum,'BYTE_BOUND')
    # JSON nesting bounded before parser recursion; strings are ASCII titles/IDs.
    depth = 0; quoted = False; escaped = False
    for char in raw:
        if quoted:
            if escaped: escaped = False
            elif char == 92: escaped = True
            elif char == 34: quoted = False
        elif char == 34: quoted = True
        elif char in (91,123):
            depth += 1; require(depth <= 8,'JSON_DEPTH')
        elif char in (93,125): depth -= 1
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(AppEvidenceError('NONFINITE_JSON')))
    except (UnicodeError,json.JSONDecodeError,RecursionError,ValueError) as error:
        if isinstance(error,AppEvidenceError): raise
        raise AppEvidenceError('MALFORMED_JSON') from error
    require(type(value) is dict,'JSON_OBJECT_REQUIRED')
    return value


@dataclass(frozen=True)
class FixtureSpec:
    fixture_id: str
    seed: int
    layout_variant: str
    target_title: str = 'Inbox'
    non_target_title: str = 'Archive'

    def __post_init__(self):
        name(self.fixture_id)
        require(len(self.fixture_id) <= 64 and integer(self.seed,0,1_000_000),'FIXTURE_ARGUMENT')
        require(self.layout_variant in ('A','B','C') and title(self.target_title) and title(self.non_target_title),'FIXTURE_ARGUMENT')

    def fields(self):
        return dict(fixture_id=self.fixture_id,layout_variant=self.layout_variant,
                    non_target_id='other',non_target_title=self.non_target_title,
                    seed=self.seed,target_id='target',target_title=self.target_title)

    @property
    def sha256(self):
        return sha256(json.dumps(self.fields(),ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class AppExpectation:
    target: OwnedTarget
    fixture: FixtureSpec
    build_mode: str

    def __post_init__(self):
        require(type(self.target) is OwnedTarget and type(self.fixture) is FixtureSpec,'EXPECTATION_TYPE')
        require(self.build_mode in ('faulty','fixed') and self.target.generation <= 2147483647,'EXPECTATION_ARGUMENT')

    def metadata(self):
        return dict(schema_version=1,package=PACKAGE,build_mode=self.build_mode,
                    fixture_id=self.fixture.fixture_id,fixture_sha256=self.fixture.sha256,
                    seed=self.fixture.seed,layout_variant=self.fixture.layout_variant,
                    run_id=self.target.run_id,generation=self.target.generation)


@dataclass(frozen=True)
class AppEvent:
    sequence: int
    timestamp_unix_ms: int
    action: str
    task_id: str
    before_title: str
    draft_title: str
    after_title: str
    cancel_count: int
    target_title: str
    non_target_title: str


@dataclass(frozen=True)
class AppSnapshot:
    expectation: AppExpectation
    sequence: int
    target_title: str
    non_target_title: str
    cancel_order: tuple[int,...]
    created_at_unix_ms: int
    updated_at_unix_ms: int
    events: tuple[AppEvent,...]
    log_sha256: str

    @property
    def explicit_cancel_flow(self):
        return (tuple(e.action for e in self.events) == ('fixture_loaded','task_open','rename_open','select_preset','cancel_edit')
                and all(e.task_id == 'target' for e in self.events[1:]) and self.cancel_order == (5,))


def validate_snapshot(state_bytes: bytes, events_bytes: bytes, expected: AppExpectation) -> AppSnapshot:
    require(type(expected) is AppExpectation,'EXPECTATION_TYPE')
    state = parse(state_bytes,1_000_000)
    require(set(state) == STATE,'STATE_FIELDS')
    metadata = expected.metadata()
    def check_meta(value):
        for key,wanted in metadata.items():
            require(type(value.get(key)) is type(wanted) and value[key] == wanted,'BINDING_'+key.upper())
    check_meta(state)
    fixture = state['fixture']
    require(type(fixture) is dict and set(fixture) == set(expected.fixture.fields()),'FIXTURE_FIELDS')
    for key,value in expected.fixture.fields().items():
        require(type(fixture[key]) is type(value) and fixture[key] == value,'FIXTURE_CONTENT')
    require(state['target_id'] == 'target' and state['non_target_id'] == 'other','TASK_IDS')
    require(title(state['target_title']) and title(state['non_target_title']),'STATE_TITLES')
    for key in ('sequence','cancel_count','created_at_unix_ms','updated_at_unix_ms'):
        require(integer(state[key],1 if key == 'sequence' else 0),'STATE_INTEGER')
    order = state['cancel_order']
    require(type(order) is list and len(order) <= 4096 and all(integer(v,1,state['sequence']) for v in order),'CANCEL_ORDER')
    require(order == sorted(set(order)) and len(order) == state['cancel_count'],'CANCEL_ORDER')
    require(type(state['last_action']) is str and state['last_action'] in ACTIONS,'STATE_ACTION')
    require(type(events_bytes) is bytes and 0 < len(events_bytes) <= 2_000_000,'EVENT_BYTE_BOUND')
    require(events_bytes.endswith(b'\n'),'TRUNCATED_EVENTS')
    lines = events_bytes.split(b'\n')[:-1]
    require(0 < len(lines) <= 4096,'EVENT_COUNT')
    events = []
    for index,line in enumerate(lines,1):
        obj = parse(line,65536)
        require(set(obj) == EVENT,'EVENT_FIELDS'); check_meta(obj)
        require(integer(obj['sequence'],1) and obj['sequence'] == index,'EVENT_SEQUENCE')
        require(integer(obj['timestamp_unix_ms']) and integer(obj['cancel_count']),'EVENT_INTEGER')
        require(type(obj['action']) is str and obj['action'] in ACTIONS and obj['task_id'] in ('','target','other'),'EVENT_ACTION')
        require(all(title(obj[k],True) for k in ('before_title','draft_title','after_title')),'EVENT_TITLES')
        require(title(obj['target_title']) and title(obj['non_target_title']),'EVENT_TITLES')
        events.append(AppEvent(**{key:obj[key] for key in AppEvent.__dataclass_fields__}))
    # Reconstruct event-level state transitions independently of build_mode.
    target,other = expected.fixture.target_title,expected.fixture.non_target_title
    selected = editing = draft = None; cancellations = []; prior_time = state['created_at_unix_ms']
    for event in events:
        require(event.timestamp_unix_ms >= prior_time,'EVENT_TIME'); prior_time = event.timestamp_unix_ms
        before = target if event.task_id == 'target' else other
        if event.sequence == 1:
            require(event.action == 'fixture_loaded' and event.task_id == '' and (event.before_title,event.draft_title,event.after_title) == ('','',''),'INITIAL_EVENT')
        elif event.action == 'task_open':
            require(editing is None and event.task_id in ('target','other'),'EVENT_TRANSITION')
            require((event.before_title,event.draft_title,event.after_title) == (before,'',before),'EVENT_TRANSITION')
            selected = event.task_id
        elif event.action == 'rename_open':
            require(editing is None and selected == event.task_id and selected is not None,'EVENT_TRANSITION')
            require((event.before_title,event.draft_title,event.after_title) == (before,before,before),'EVENT_TRANSITION')
            editing,draft = selected,before
        elif event.action == 'select_preset':
            require(editing == event.task_id and editing is not None,'EVENT_TRANSITION')
            require((event.before_title,event.draft_title,event.after_title) == (before,'Today',before),'EVENT_TRANSITION')
            draft = 'Today'
        elif event.action in ('cancel_edit','dismiss_edit','save_edit'):
            require(editing == event.task_id and editing is not None,'EVENT_TRANSITION')
            require((event.before_title,event.draft_title) == (before,draft),'EVENT_TRANSITION')
            allowed = (before,draft) if event.action == 'cancel_edit' else ((draft,) if event.action == 'save_edit' else (before,))
            require(event.after_title in allowed,'EVENT_TRANSITION')
            if event.task_id == 'target': target = event.after_title
            else: other = event.after_title
            if event.action == 'cancel_edit': cancellations.append(event.sequence)
            editing = draft = None
        else:
            raise AppEvidenceError('EVENT_TRANSITION')
        require(event.cancel_count == len(cancellations),'EVENT_CANCEL_COUNT')
        require((event.target_title,event.non_target_title) == (target,other),'EVENT_PERSISTED_TITLES')
        require(other == expected.fixture.non_target_title,'NON_TARGET_CHANGED')
    last = events[-1]
    require(state['sequence'] == last.sequence,'TERMINAL_SEQUENCE')
    require(state['last_action'] == last.action and state['updated_at_unix_ms'] == last.timestamp_unix_ms,'TERMINAL_METADATA')
    require(state['updated_at_unix_ms'] >= state['created_at_unix_ms'],'STATE_TIME')
    require((state['target_title'],state['non_target_title']) == (target,other),'TERMINAL_TITLES')
    require(order == cancellations,'TERMINAL_CANCEL_ORDER')
    log_hash = sha256(expected.target.binding.encode()+len(state_bytes).to_bytes(8,'big')+state_bytes+events_bytes).hexdigest()
    return AppSnapshot(expected,last.sequence,target,other,tuple(order),state['created_at_unix_ms'],state['updated_at_unix_ms'],tuple(events),log_hash)


@dataclass(frozen=True)
class AppObservation:
    reason_code: str
    snapshot: AppSnapshot | None
    read_sha256: tuple[str,...]
    coherent: bool
    atomic: bool = False


class AppStateReader:
    def __init__(self, transport): self.transport = transport

    def collect(self, expected: AppExpectation, deadline: float) -> AppObservation:
        hashes = []
        try:
            require(expected.target == self.transport.target,'TRANSPORT_BINDING')
            # All mutation windows between state/event reads are bracketed. Equality
            # cannot exclude an ABA change, so this is never atomic attestation.
            self.transport.discover(deadline)
            reads = []
            for kind in ('state','events','state','events','state'):
                raw = self.transport.read_app_state(deadline) if kind == 'state' else self.transport.read_app_events(deadline)
                reads.append(raw); hashes.append(sha256(raw).hexdigest())
            self.transport.discover(deadline)
            require(reads[0] == reads[2] == reads[4] and reads[1] == reads[3],'READ_WINDOW_CHANGED')
            snapshot = validate_snapshot(reads[0],reads[1],expected)
            return AppObservation('COHERENT',snapshot,tuple(hashes),True)
        except AppEvidenceError as error:
            return AppObservation(error.reason_code,None,tuple(hashes),False)
        except (RuntimeStop,TimeoutError,UnicodeError):
            return AppObservation('READ_UNAVAILABLE',None,tuple(hashes),False)


@dataclass(frozen=True)
class RunProof:
    reset_snapshot: AppSnapshot
    task_sha256: str
    script_sha256: str
    trace_completed: bool
    preconditions_verified: bool


def oracle_fields(case_spec, observation: AppObservation, proof: RunProof) -> dict:
    """Fields for existing repro_oracle.OracleRun(**fields), not a judge decision.

    RunProof is trusted host evidence. No model response may instantiate it.
    The API cannot itself attest parent traces, capture source or reset dispatch.
    """
    require(type(observation) is AppObservation and observation.coherent and observation.snapshot is not None,'ORACLE_UNUSABLE')
    require(type(proof) is RunProof and type(proof.reset_snapshot) is AppSnapshot,'PROOF_TYPE')
    digest(proof.task_sha256); digest(proof.script_sha256)
    for value in (proof.trace_completed,proof.preconditions_verified): require(type(value) is bool,'PROOF_BOOL')
    snap,reset = observation.snapshot,proof.reset_snapshot
    expectation = snap.expectation
    require(reset.expectation == expectation and reset.sequence == 1 and len(reset.events) == 1 and reset.events[0].action == 'fixture_loaded' and not reset.cancel_order,'FRESH_RESET_REQUIRED')
    require(reset.created_at_unix_ms == snap.created_at_unix_ms,'RESET_TIME_MISMATCH')
    require(case_spec.fixture_sha256 == expectation.fixture.sha256 and case_spec.task_sha256 == proof.task_sha256,'CASE_BINDING')
    digest(case_spec.faulty_build_sha256); digest(case_spec.repaired_build_sha256)
    require(case_spec.faulty_build_sha256 != case_spec.repaired_build_sha256,'CASE_BUILDS_IDENTICAL')
    wanted = case_spec.faulty_build_sha256 if expectation.build_mode == 'faulty' else case_spec.repaired_build_sha256
    require(expectation.target.apk_sha256 == wanted,'CASE_BUILD_BINDING')
    name(case_spec.case_id); name(case_spec.oracle_name)
    require(expectation.fixture.target_title != 'Today','NONDISCRIMINATING_FIXTURE')
    complete = proof.trace_completed and proof.preconditions_verified and snap.explicit_cancel_flow
    failure = snap.target_title != expectation.fixture.target_title if complete else None
    return dict(run_id=expectation.target.run_id,case_id=case_spec.case_id,
                task_sha256=proof.task_sha256,fixture_sha256=expectation.fixture.sha256,
                build_sha256=expectation.target.apk_sha256,oracle_name=case_spec.oracle_name,
                oracle_log_sha256=snap.log_sha256,completed=complete,
                preconditions_verified=proof.preconditions_verified,goal_reached=complete,
                failure_observed=failure,generation=expectation.target.generation,visual_match=False)
