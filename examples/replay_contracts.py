"""Small OFFLINE contracts for provided synthetic tap-button evidence.

No XML/ADB capture, network, device input, filesystem output or attestation.
Matching capture metadata is a consistency check, NOT atomic capture proof.
Trusted producers supply evidence and pair binding; production must verify it.
AttemptBudget is in-memory and is NOT a durable lease, billing or action ledger.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
from threading import Lock
from typing import Callable

from evaluation_metrics import EvaluationRow
from repro_oracle import (CaseSpec, Decision, OracleRun, Verdict, judge_release,
                          run_identity_matches, independent_receipts)


def _text(value: object, maximum: int = 256, *, empty: bool = False) -> None:
    if type(value) is not str or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError('invalid bounded text')


def _integer(value: object, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid bounded integer')


def _digest(value: object) -> None:
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('expected lowercase SHA-256')


def _number(value: object, low: float, high: float) -> float:
    # Bounds before float conversion also reject huge integers without overflow.
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError('invalid finite bounded number')
    if type(value) is float and not math.isfinite(value):
        raise ValueError('nonfinite number')
    return float(value)


def pixel(value: object, extent: int) -> int:
    """Exact ints or finite integral floats only; NEVER truncate fractional input."""
    _integer(extent, 1, 16384)
    if type(value) is int:
        result = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        if not 0 <= value < extent:
            raise ValueError('pixel outside frame')
        result = int(value)
    else:
        raise ValueError('integer pixel required')
    if not 0 <= result < extent:
        raise ValueError('pixel outside frame')
    return result


@dataclass(frozen=True)
class PreActionFrame:
    run_id: str
    serial: str
    boot_id: str
    package: str
    build_sha256: str
    generation: int
    capture_epoch: int
    frame_sha256: str
    width: int
    height: int
    expected_screen: str


@dataclass(frozen=True)
class Node:
    node_key: str
    resource_id: str
    text: str
    clickable: bool
    bounds: tuple[int, int, int, int]  # left/top inclusive, right/bottom exclusive


@dataclass(frozen=True)
class Hierarchy:
    frame: PreActionFrame
    hierarchy_sha256: str
    nodes: tuple[Node, ...]


@dataclass(frozen=True)
class Locator:
    resource_id: str
    visible_text: str
    expected_screen: str


@dataclass(frozen=True)
class TraceClick:
    frame: PreActionFrame
    hierarchy: Hierarchy
    x: int | float
    y: int | float


def validate_capture(frame: PreActionFrame, hierarchy: Hierarchy,
                     current: PreActionFrame) -> None:
    if type(hierarchy) is not Hierarchy:
        raise ValueError('typed hierarchy required')
    # Validate EVERY binding before equality: bool(True) equals int(1).
    for bound in (frame, current, hierarchy.frame):
        if type(bound) is not PreActionFrame:
            raise ValueError('typed frame required')
        for name in ('run_id', 'serial', 'boot_id', 'package', 'expected_screen'):
            _text(getattr(bound, name))
        _digest(bound.build_sha256); _digest(bound.frame_sha256)
        _integer(bound.generation, 1, 2**63-1)
        _integer(bound.capture_epoch, 1, 2**63-1)
        _integer(bound.width, 1, 16384); _integer(bound.height, 1, 16384)
    if frame != current or hierarchy.frame != frame:
        raise ValueError('stale or inconsistent capture identity/epoch/generation')
    _digest(hierarchy.hierarchy_sha256)
    if type(hierarchy.nodes) is not tuple or not 1 <= len(hierarchy.nodes) <= 128:
        raise ValueError('bounded immutable button nodes required')
    seen = set()
    for node in hierarchy.nodes:
        if type(node) is not Node:
            raise ValueError('typed node required')
        _text(node.node_key); _text(node.resource_id); _text(node.text, empty=True)
        if node.node_key in seen:
            raise ValueError('duplicate node key')
        seen.add(node.node_key)
        if not node.resource_id.startswith(frame.package + ':id/') or len(node.resource_id) <= len(frame.package) + 4:
            raise ValueError('resource outside app')
        if type(node.clickable) is not bool or type(node.bounds) is not tuple or len(node.bounds) != 4:
            raise ValueError('invalid node flags/bounds')
        left, top, right, bottom = node.bounds
        for value in node.bounds:
            _integer(value, 0, 16384)
        if not (0 <= left < right <= frame.width and 0 <= top < bottom <= frame.height):
            raise ValueError('invalid node rectangle')


def _locator(locator: Locator, package: str) -> None:
    if type(locator) is not Locator:
        raise ValueError('typed locator required')
    _text(locator.resource_id); _text(locator.visible_text, empty=True)
    _text(locator.expected_screen)
    if not locator.resource_id.startswith(package + ':id/') or len(locator.resource_id) <= len(package) + 4:
        raise ValueError('locator outside app')


def lift_click(click: TraceClick, current: PreActionFrame) -> Locator:
    """Fail closed on 0 or multiple clickable hits, including nested buttons."""
    if type(click) is not TraceClick:
        raise ValueError('typed click required')
    validate_capture(click.frame, click.hierarchy, current)
    x, y = pixel(click.x, current.width), pixel(click.y, current.height)
    hits = [n for n in click.hierarchy.nodes if n.clickable
            and n.bounds[0] <= x < n.bounds[2] and n.bounds[1] <= y < n.bounds[3]]
    if len(hits) != 1:
        raise ValueError('ambiguous or missing clickable hit')
    target = hits[0]
    locator = Locator(target.resource_id, target.text, current.expected_screen)
    # Even a geometrically unique hit must have a unique semantic selector.
    resolve(locator, current, click.hierarchy, current)
    return locator


def resolve(locator: Locator, frame: PreActionFrame, hierarchy: Hierarchy,
            current: PreActionFrame) -> tuple[int, int]:
    """No stored coordinates: resolve ONE current button and return its center."""
    validate_capture(frame, hierarchy, current)
    _locator(locator, frame.package)
    if locator.expected_screen != frame.expected_screen:
        raise ValueError('unexpected current screen')
    matches = [n for n in hierarchy.nodes if n.clickable
               and n.resource_id == locator.resource_id and n.text == locator.visible_text]
    if len(matches) != 1:
        raise ValueError('semantic selector must match exactly once')
    left, top, right, bottom = matches[0].bounds
    return (left + right - 1)//2, (top + bottom - 1)//2


@dataclass(frozen=True)
class SemanticExport:
    package: str
    task_sha256: str
    fixture_sha256: str
    steps: tuple[Locator, ...]
    schema_version: int = 1
    resolver_version: str = 'tap-buttons-v1'

    def to_bytes(self) -> bytes:
        _text(self.package); _digest(self.task_sha256); _digest(self.fixture_sha256)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('unsupported schema')
        _text(self.resolver_version, 64)
        if self.resolver_version != 'tap-buttons-v1':
            raise ValueError('unsupported resolver')
        if type(self.steps) is not tuple or not 1 <= len(self.steps) <= 24:
            raise ValueError('invalid bounded steps')
        for locator in self.steps:
            _locator(locator, self.package)
        # No oracle values, original pixels, timestamps or self-referential hash.
        return json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('utf-8')

    def digest(self) -> str:
        return sha256(self.to_bytes()).hexdigest()


def export_trace(trace: tuple[TraceClick, ...], task_sha256: str,
                 fixture_sha256: str) -> SemanticExport:
    if type(trace) is not tuple or not 1 <= len(trace) <= 24:
        raise ValueError('bounded immutable trace required')
    _digest(task_sha256); _digest(fixture_sha256)
    if any(type(click) is not TraceClick for click in trace):
        raise ValueError('typed trace required')
    first = trace[0].frame
    if type(first) is not PreActionFrame:
        raise ValueError('typed frame required')
    identity = lambda f: (f.run_id, f.serial, f.boot_id, f.package, f.build_sha256, f.generation)
    steps, epoch = [], 0
    for click in trace:
        validate_capture(click.frame, click.hierarchy, click.frame)
        if identity(click.frame) != identity(first) or click.frame.capture_epoch <= epoch:
            raise ValueError('mixed run or non-increasing capture epoch')
        steps.append(lift_click(click, click.frame))
        epoch = click.frame.capture_epoch
    result = SemanticExport(first.package, task_sha256, fixture_sha256, tuple(steps))
    result.to_bytes()
    return result


@dataclass(frozen=True)
class CollectedPair:
    decision: Decision
    row: EvaluationRow


def _complete(spec: CaseSpec, run: OracleRun | None, build: str, generation: int) -> bool:
    return (run_identity_matches(spec, run, build, generation)
            and run.completed and run.preconditions_verified and run.goal_reached)


def collect_pair(spec: CaseSpec, faulty: OracleRun | None, repaired: OracleRun | None,
                 generation: int, *, export_created: bool,
                 pair_binding_valid: bool) -> CollectedPair:
    """Caller cannot supply a verdict. Binding bool is trusted, NOT attested here."""
    if type(spec) is not CaseSpec or any(r is not None and type(r) is not OracleRun
                                        for r in (faulty, repaired)):
        raise ValueError('typed case/runs required')
    if type(export_created) is not bool or type(pair_binding_valid) is not bool:
        raise ValueError('exact bool evidence flags required')
    decision = judge_release(spec, faulty, repaired, generation,
                             export_created=export_created, pair_binding_valid=pair_binding_valid)
    fc = bool(_complete(spec, faulty, spec.faulty_build_sha256, generation))
    rc = bool(_complete(spec, repaired, spec.repaired_build_sha256, generation))
    if faulty is not None and repaired is not None and not independent_receipts(faulty, repaired):
        rc = False  # Shared/malformed evidence is not a usable independent control.
    fs = faulty.failure_observed if fc and type(faulty.failure_observed) is bool else None
    rs = repaired.failure_observed if rc and type(repaired.failure_observed) is bool else None
    if (not export_created or not pair_binding_valid or
        (decision.verdict is Verdict.CONFIRMED and not (fc and rc and fs is True and rs is False))):
        decision = replace(decision, verdict=Verdict.INCONCLUSIVE,
                           reason='export or trusted replay binding/completion evidence missing')
    row = EvaluationRow(spec.case_id, export_created, fc, fs, rc, rs,
                        pair_binding_valid, decision.verdict)
    return CollectedPair(decision, row)


@dataclass(frozen=True)
class AttemptCounts:
    calls: int
    actions: int
    captures: int


class AttemptBudget:
    """Reserve each attempt BEFORE dispatch; no refunds, no durable recovery.

    Calls count each exploratory model request attempt (timeouts included).
    Actions count each explicit driver action attempt, independently of batches.
    Captures count implicit evidence reads separately. Caller must reserve each
    batch action separately; this class does not dispatch or parse batches.
    """
    def __init__(self, *, clock: Callable[[], float], max_calls: int = 12,
                 max_actions: int = 24, max_captures: int = 64,
                 seconds: float = 120):
        if not callable(clock):
            raise ValueError('clock must be callable')
        for value in (max_calls, max_actions, max_captures):
            _integer(value, 1, 10000)
        self._seconds = _number(seconds, 0.001, 3600)
        self._clock = clock
        self._started = self._last = _number(clock(), 0, 10**15)
        self._limits = dict(calls=max_calls, actions=max_actions, captures=max_captures)
        self._used = dict(calls=0, actions=0, captures=0)
        self._lock = Lock()

    def _reserve(self, kind: str) -> None:
        with self._lock:
            now = _number(self._clock(), 0, 10**15)
            if now < self._last:
                raise ValueError('clock moved backwards')
            self._last = now
            if now - self._started >= self._seconds:
                raise ValueError('wall time budget exhausted')
            if self._used[kind] >= self._limits[kind]:
                raise ValueError(kind + ' attempt budget exhausted')
            self._used[kind] += 1

    def reserve_call(self) -> None:
        self._reserve('calls')

    def reserve_action(self) -> None:
        self._reserve('actions')

    def reserve_capture(self) -> None:
        self._reserve('captures')

    def snapshot(self) -> AttemptCounts:
        with self._lock:
            return AttemptCounts(**self._used)
