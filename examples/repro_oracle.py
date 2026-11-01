"""ReproLoop reference: independent oracle + repaired-build negative control.

This is an OFFLINE SYNTHETIC fixture, not Android integration, Meta inference,
logcat authentication or a proof of bug-root-cause identity. Only the trusted
runner may construct OracleRun from app/test state; never accept a model's JSON
as that source. Production code must pin emulator/app identity and attest logs.
"""
from __future__ import annotations
from dataclasses import dataclass, replace, asdict
from enum import StrEnum
from hashlib import sha256
import json
import sqlite3
from threading import Lock

class Verdict(StrEnum):
    CONFIRMED='reproduced_oracle_and_control_confirmed'
    NOT_REPRODUCED='not_reproduced'
    VISUAL_ONLY='visual_match_not_confirmed'
    INCONCLUSIVE='inconclusive'

@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    task_sha256: str
    fixture_sha256: str
    faulty_build_sha256: str
    repaired_build_sha256: str
    oracle_name: str

@dataclass(frozen=True)
class OracleRun:
    run_id: str
    case_id: str
    task_sha256: str
    fixture_sha256: str
    build_sha256: str
    oracle_name: str
    oracle_log_sha256: str
    completed: bool
    preconditions_verified: bool
    goal_reached: bool
    failure_observed: bool | None
    generation: int
    visual_match: bool=False

@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    faulty_run: str | None=None
    repaired_run: str | None=None
    generation: int=0
    case_manifest_sha256: str=""


def valid_name(value, maximum=128):
    return type(value) is str and 0 < len(value) <= maximum and value == value.strip() and bool(value)


def valid_digest(value):
    return (type(value) is str and len(value) == 64
            and all(c in '0123456789abcdef' for c in value))


def validate_spec(spec):
    if (type(spec) is not CaseSpec or not valid_name(spec.case_id) or
        not valid_name(spec.oracle_name) or not all(valid_digest(v) for v in
        (spec.task_sha256, spec.fixture_sha256, spec.faulty_build_sha256,
         spec.repaired_build_sha256))):
        raise ValueError('invalid bounded case identity/digests')


def valid_run_shape(run):
    return (type(run) is OracleRun and valid_name(run.run_id)
        and valid_name(run.case_id) and valid_name(run.oracle_name)
        and all(valid_digest(x) for x in (run.task_sha256, run.fixture_sha256,
                                         run.build_sha256, run.oracle_log_sha256))
        and all(type(x) is bool for x in (run.completed, run.preconditions_verified,
                                         run.goal_reached, run.visual_match))
        and (run.failure_observed is None or type(run.failure_observed) is bool)
        and type(run.generation) is int and 1 <= run.generation <= 2**63-1)


def run_identity_matches(spec, run, build, generation):
    return (valid_run_shape(run) and run.case_id == spec.case_id
        and run.task_sha256 == spec.task_sha256 and run.fixture_sha256 == spec.fixture_sha256
        and run.build_sha256 == build and run.oracle_name == spec.oracle_name
        and run.generation == generation)


def independent_receipts(faulty, repaired):
    # Each declared log receipt includes its own run/build/state evidence.
    # This is byte-identity consistency, NOT attestation of two real executions.
    return (valid_run_shape(faulty) and valid_run_shape(repaired)
        and faulty.run_id != repaired.run_id
        and faulty.build_sha256 != repaired.build_sha256
        and faulty.oracle_log_sha256 != repaired.oracle_log_sha256)


def judge(spec: CaseSpec, faulty: OracleRun | None, repaired: OracleRun | None,
          current_generation: int) -> Decision:
    if type(current_generation) is not int or not 1 <= current_generation <= 2**63-1:
        raise ValueError('invalid current generation')
    validate_spec(spec)
    case_digest=sha256(json.dumps(asdict(spec),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def result(verdict,reason,faulty_run=None,repaired_run=None):
        return Decision(verdict,reason,faulty_run,repaired_run,current_generation,case_digest)
    if spec.faulty_build_sha256==spec.repaired_build_sha256:
        return result(Verdict.INCONCLUSIVE,'negative control must use distinct fixed build')
    if faulty is None:
        return result(Verdict.INCONCLUSIVE,'missing faulty-build run')
    if not run_identity_matches(spec,faulty,spec.faulty_build_sha256,current_generation):
        return result(Verdict.INCONCLUSIVE,'faulty run identity/generation mismatch')
    if not (faulty.completed and faulty.preconditions_verified and faulty.goal_reached):
        return result(Verdict.INCONCLUSIVE,'incomplete execution or setup not verified')
    if type(faulty.failure_observed) is not bool:
        return result(Verdict.VISUAL_ONLY if faulty.visual_match else Verdict.INCONCLUSIVE,
                      'no independent oracle signal',faulty.run_id)
    if faulty.failure_observed is False:
        return result(Verdict.NOT_REPRODUCED,'independent oracle did not observe target symptom',faulty.run_id)
    if repaired is None:
        return result(Verdict.INCONCLUSIVE,'positive oracle present but repaired-build control missing',faulty.run_id)
    if (not run_identity_matches(spec,repaired,spec.repaired_build_sha256,current_generation)
        or not independent_receipts(faulty,repaired)):
        return result(Verdict.INCONCLUSIVE,'control identity/generation/shared-receipt mismatch',faulty.run_id)
    if not (repaired.completed and repaired.preconditions_verified and repaired.goal_reached):
        return result(Verdict.INCONCLUSIVE,'control did not execute equivalent goal completely',faulty.run_id,repaired.run_id)
    if repaired.failure_observed is not False:
        return result(Verdict.INCONCLUSIVE,'control still fails or has no independent signal',faulty.run_id,repaired.run_id)
    return result(Verdict.CONFIRMED,'predeclared target oracle on faulty build only; repaired control negative',faulty.run_id,repaired.run_id)


def judge_release(spec, faulty, repaired, generation, *, export_created=False, pair_binding_valid=False):
    """Provided trusted evidence only; no raw log/script/reset authentication."""
    if type(export_created) is not bool or type(pair_binding_valid) is not bool:
        raise ValueError('exact bool release evidence required')
    decision = judge(spec, faulty, repaired, generation)
    if not export_created or not pair_binding_valid:
        decision = replace(decision, verdict=Verdict.INCONCLUSIVE,
                           reason='export or trusted replay binding evidence missing')
    return decision


class TerminalReceiptStore:
    """SQLite receipts for this LOCAL decision, not an external write guarantee.

    A cancellation generation invalidates later stale decisions. A duplicate
    same-key/same-bytes return must not repeat a real action. Unknown external
    side effects must be reconciled separately before publishing this receipt.
    """
    def __init__(self):
        self.db=sqlite3.connect(':memory:',check_same_thread=False)
        self.db.execute('CREATE TABLE fence (onlyrow INTEGER PRIMARY KEY CHECK(onlyrow=1), generation INTEGER NOT NULL)')
        self.db.execute('INSERT INTO fence VALUES(1,1)')
        self.db.execute('CREATE TABLE receipts (request_id TEXT PRIMARY KEY NOT NULL CHECK(length(request_id)>0), digest TEXT NOT NULL, payload TEXT NOT NULL)')
        self.db.commit();self.lock=Lock()
    def generation(self):
        with self.lock:return self.db.execute('SELECT generation FROM fence WHERE onlyrow=1').fetchone()[0]
    def cancel(self):
        with self.lock:
            self.db.execute('UPDATE fence SET generation=generation+1 WHERE onlyrow=1');self.db.commit()
    def save(self, request_id, spec, faulty, repaired, generation, *,
             export_created=False, pair_binding_valid=False):
        """Compute from provided evidence under the lock; no caller Decision.

        Trusted Python can still fabricate run evidence. This API prevents
        accidental verdict insertion, not malicious-producer forgery/authorship.
        """
        if not valid_name(request_id, 120):
            raise ValueError('invalid bounded request id')
        if type(generation) is not int or not 1 <= generation <= 2**63-1:
            raise ValueError('invalid generation')
        validate_spec(spec)
        if any(run is not None and not valid_run_shape(run) for run in (faulty,repaired)):
            raise ValueError('invalid bounded run evidence')
        if any(run is not None and run.generation != generation for run in (faulty,repaired)):
            raise ValueError('run evidence generation mismatch')
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                if self.db.execute('SELECT generation FROM fence WHERE onlyrow=1').fetchone()[0]!=generation:
                    raise ValueError('stale cancelled generation')
                decision=judge_release(spec,faulty,repaired,generation,
                    export_created=export_created,pair_binding_valid=pair_binding_valid)
                evidence={'spec':asdict(spec),'faulty':None if faulty is None else asdict(faulty),
                    'repaired':None if repaired is None else asdict(repaired),'generation':generation,
                    'export_created':export_created,'pair_binding_valid':pair_binding_valid}
                digest=sha256(json.dumps(evidence,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
                payload=json.dumps(asdict(decision),sort_keys=True,separators=(',',':'),allow_nan=False)
                old=self.db.execute('SELECT digest,payload FROM receipts WHERE request_id=?',(request_id,)).fetchone()
                if old:
                    if old[0]!=digest:raise ValueError('same request id, conflicting evidence')
                    self.db.commit();return False,json.loads(old[1])
                self.db.execute('INSERT INTO receipts VALUES(?,?,?)',(request_id,digest,payload))
                self.db.commit();return True,json.loads(payload)
            except BaseException:
                self.db.rollback();raise
    def close(self):self.db.close()


def synthetic_demo():
    """F01: selecting a rename preset then Cancel must preserve stored title.

    Controlled Python state only. Both builds complete the same three semantic
    actions; no Android APK or Meta model is involved.
    """
    h=lambda value:sha256(value.encode()).hexdigest()
    actions=['open_rename','select_preset_Today','cancel']
    task=json.dumps(actions,separators=(',',':'))
    spec=CaseSpec('F01-rename-cancel',h(task),h('stored_title=Inbox'),
        h('faulty-source-v1'),h('repaired-source-v2'),'cancel_preserves_stored_title')
    def run(build,persists_preset):
        before='Inbox';after='Today' if persists_preset else before
        raw=json.dumps({'actions':actions,'before':before,'after':after,
                        'expected':before},sort_keys=True)
        return OracleRun('run-'+build[:8],spec.case_id,spec.task_sha256,
            spec.fixture_sha256,build,spec.oracle_name,h(raw),True,True,True,
            after!=before,1,True)
    faulty=run(spec.faulty_build_sha256,True)
    fixed=run(spec.repaired_build_sha256,False)
    decision=judge(spec,faulty,fixed,1)
    return {'evidence_level':'SYNTHETIC_MOCK_TESTED','meta_calls':0,'android_runs':0,
        'fault_family':'F01_rename_cancel_persistence','actions':actions,
        'decision':{'verdict':decision.verdict,'reason':decision.reason},
        'limits':'Controlled Python state, NOT actual bug reproduction on an Android app.'}

if __name__=='__main__':print(json.dumps(synthetic_demo(),indent=2))
