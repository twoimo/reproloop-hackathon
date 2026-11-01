"""Model-free runtime replay. No model, HTTP, browser or credential dependency.

Application oracle remains in runtime.app_state; pair binding belongs to parent.
The examples contracts must be importable by the trusted application entrypoint.
"""
from dataclasses import dataclass, asdict
from hashlib import sha256
from replay_contracts import SemanticExport
from repro_oracle import CaseSpec, OracleRun, validate_spec
from .lab import OwnedLab, canonical, save_blob
from .runtime.owned import PACKAGE, RuntimeStop
from .runtime.driver import ActionRequest
from .runtime.app_state import RunProof, oracle_fields


@dataclass(frozen=True)
class ReplayResult:
    oracle_run: OracleRun | None
    run_proof: RunProof | None
    reset_receipt_sha256: str
    trace_sha256: str
    script_sha256: str
    model_calls: int
    complete: bool
    reason: str
    evidencepaths: tuple[str, ...]


def visible(frame, suffix, text):
    return any(n.resource_id == PACKAGE+':id/'+suffix and n.text == text and n.clickable for n in frame.nodes)


def phase(frame):
    if visible(frame,'cancel_edit','Cancel'): return 'rename'
    if visible(frame,'rename_open','Rename'): return 'selected'
    if any(n.clickable and n.resource_id in (PACKAGE+':id/task_target',PACKAGE+':id/task_other') for n in frame.nodes): return 'tasks'
    raise RuntimeStop('unknown visible screen')


def model_free_replay(lab: OwnedLab, export: SemanticExport, spec: CaseSpec, mode: str,
                      run_id: str, generation: int = 1, seconds=120) -> ReplayResult:
    run = None; proof = None; oracle = None; traces = []; paths = []
    script_hash = reset_hash = ''; complete = False; reason = 'not started'
    try:
        if type(export) is not SemanticExport: raise ValueError('typed semantic export required')
        validate_spec(spec)
        raw = export.to_bytes(); script_hash = sha256(raw).hexdigest()
        if export.package != PACKAGE or export.task_sha256 != spec.task_sha256 or export.fixture_sha256 != spec.fixture_sha256:
            raise RuntimeStop('export case mismatch')
        if mode not in ('faulty','fixed'): raise ValueError('mode')
        wanted = spec.faulty_build_sha256 if mode == 'faulty' else spec.repaired_build_sha256
        if lab.apk_sha256(mode) != wanted: raise RuntimeStop('case build mismatch')
        fixture = lab.fixtures.get(spec.fixture_sha256)
        if fixture is None: raise RuntimeStop('fixture must be registered before replay')
        # F01 requires exactly these semantic steps and their actual visible labels.
        expected = (('task_target','Target task: '+fixture.target_title,'tasks'),
                    ('rename_open','Rename','selected'), ('preset_today','Today','rename'),
                    ('cancel_edit','Cancel','rename'))
        if tuple((x.resource_id,x.visible_text,x.expected_screen) for x in export.steps) != tuple((PACKAGE+':id/'+rid,text,screen) for rid,text,screen in expected):
            raise RuntimeStop('script is not explicit target rename/Today/Cancel flow')
        paths.append(save_blob(lab.config.evidence_root,raw,'.script.json'))
        run = lab.prepare(fixture,mode,run_id,generation,seconds)
        reset_hash = sha256(canonical(run.reset_receipt)).hexdigest()
        reset = run.reset_observation.snapshot
        if reset is None or reset.sequence != 1: raise RuntimeStop('fresh reset missing')
        for index, locator in enumerate(export.steps):
            frame = run.driver.capture()
            if phase(frame) != locator.expected_screen: raise RuntimeStop('visible screen mismatch')
            frame.resolve(locator.resource_id,locator.visible_text)
            def post(after, step=index):
                if step in (0,3): return phase(after) == 'selected' and visible(after,'rename_open','Rename')
                if step == 1: return phase(after) == 'rename' and visible(after,'preset_today','Today') and visible(after,'cancel_edit','Cancel')
                return phase(after) == 'rename' and any(n.text == 'Draft: Today' for n in after.nodes)
            receipt = run.driver.execute(ActionRequest(run_id+'.a'+str(index),run_id+'.r'+str(index),
                        'tap',frame.evidence_sha256,locator.resource_id,locator.visible_text),frame,post)
            traces.append(dict(index=index,locator=asdict(locator),pre=frame.evidence(),receipt=asdict(receipt)))
            if receipt.state != 'ACCEPTED': raise RuntimeStop('action '+receipt.state)
            last = run.last_frame
            if last is None or receipt.evidence != last.evidence(): raise RuntimeStop('post-frame evidence mismatch')
        observation = run.driver.collect_app_state(run.expectation)
        proof = RunProof(reset,spec.task_sha256,script_hash,True,True)
        oracle = OracleRun(**oracle_fields(spec,observation,proof))
        complete = oracle.completed
        reason = 'completed explicit cancel trace' if complete else 'terminal flow incomplete'
    except (ValueError,RuntimeError,OSError) as error:
        reason = type(error).__name__+': '+str(error)
    finally:
        if run is not None:
            paths.extend(run.transport.evidencepaths)
            with lab.journal.locked() as db:
                journal_record = {table:[dict(row) for row in db.execute('SELECT * FROM '+table+' WHERE binding=?',(run.target.binding,))] for table in ('actions','lab_setup','run_history')}
            paths.append(save_blob(lab.config.evidence_root,canonical(journal_record),'.journal.json'))
            if proof is not None:
                paths.append(save_blob(lab.config.evidence_root,canonical(asdict(proof)),'.proof.json'))
            try: lab.finish(run)
            except RuntimeStop as error:
                complete = False; reason += '; retained fence: '+str(error)
    # Trace contains runtime receipts, not a model's claimed action history.
    version_paths = [__file__]
    from .runtime import owned, driver, app_state
    version_paths += [owned.__file__,driver.__file__,app_state.__file__]
    from pathlib import Path
    record = dict(schema_version=1,run_id=run_id,generation=generation,mode=mode,
                  script_sha256=script_hash,reset_receipt_sha256=reset_hash,
                  target=asdict(run.target) if run else None,steps=traces,complete=complete,reason=reason,
                  source_sha256={Path(p).name:sha256(Path(p).read_bytes()).hexdigest() for p in version_paths},
                  model_calls=0,no_model_basis='architectural dependency exclusion, not network attestation')
    trace_raw = canonical(record)
    paths.append(save_blob(lab.config.evidence_root,trace_raw,'.trace.json'))
    return ReplayResult(oracle,proof,reset_hash,sha256(trace_raw).hexdigest(),script_hash,0,complete,reason,tuple(paths))
