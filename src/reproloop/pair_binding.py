"""Read-only byte-link validator, not native/producer attestation."""
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import stat
from replay_contracts import SemanticExport, CollectedPair, collect_pair
from repro_oracle import CaseSpec, OracleRun, validate_spec
from .runtime.owned import OwnedTarget, Frame, PACKAGE, png_size, parse_hierarchy, digest, name
from .runtime.app_state import (FixtureSpec, AppExpectation, AppObservation, RunProof,
                                validate_snapshot, oracle_fields)
from .replay import phase, visible


@dataclass(frozen=True)
class BindingReport:
    valid: bool
    reason: str
    collected_pair: CollectedPair | None
    proof: dict


def require(condition, reason):
    if not condition: raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def equal(a, b, reason): require(canonical(a) == canonical(b), reason)


def strict_json(raw):
    require(type(raw) is bytes and len(raw) <= 16_777_216, 'JSON byte bound')
    def pairs(items):
        result = {}
        for k,v in items:
            require(k not in result, 'duplicate JSON key'); result[k] = v
        return result
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    def check(v, depth=0):
        require(depth <= 32, 'JSON depth bound')
        if isinstance(v,dict):
            for x in v.values(): check(x,depth+1)
        elif isinstance(v,list):
            require(len(v) <= 4096, 'JSON list bound')
            for x in v: check(x,depth+1)
    check(value)
    return value


def lexical_absolute(path):
    text = os.fspath(path)
    require(type(text) is str and text.startswith('/') and
            all(x not in ('', '.', '..') for x in text.split('/')[1:]),
            'canonical absolute path required')
    require('://' not in text and '\\' not in text, 'URL/backslash forbidden')
    return Path(text)


class Files:
    def __init__(self, root, original_evidence_root=None):
        self.root = lexical_absolute(root)
        require(self.root == self.root.resolve() and self.root.is_dir(), 'root must be real directory')
        self.original_root = (lexical_absolute(original_evidence_root)
                              if original_evidence_root is not None else None)
        self.cache = {}; self.total = 0

    def read(self, path, *, result=False):
        p = lexical_absolute(path)
        if not result and self.original_root is not None:
            # Pure lexical mapping: never stat/resolve/open the historical host.
            if p.is_relative_to(self.root):
                pass  # addressed() already names the current actual root.
            elif p.is_relative_to(self.original_root):
                p = self.root / p.relative_to(self.original_root)
            else:
                raise ValueError('unmapped evidence path')
        base = self.root.parent if result else self.root
        require(p.is_relative_to(base), 'path escapes allowed root')
        for candidate in (p,*p.parents):
            require(not candidate.is_symlink(), 'symlink forbidden')
            if candidate == base: break
        if p in self.cache:
            raw = self.cache[p]
            if not result: self.check_address(p, raw)
            return raw
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= 16_777_216, 'regular bounded file required')
            with os.fdopen(fd, 'rb', closefd=False) as stream: raw = stream.read(16_777_217)
            after = os.fstat(fd)
            require(len(raw) == st.st_size and (st.st_size,st.st_mtime_ns,st.st_ctime_ns) == (after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'file changed/byte bound')
        finally: os.close(fd)
        self.total += len(raw); require(self.total <= 268_435_456, 'pair byte budget')
        if not result: self.check_address(p, raw)
        self.cache[p] = raw
        return raw

    @staticmethod
    def check_address(p, raw):
        require(re.fullmatch(r'[0-9a-f]{64}\.(?:png|xml|[a-z]+\.json|events\.jsonl)', p.name) is not None,
                'content address filename')
        require(sha256(raw).hexdigest() == p.name[:64], 'content hash mismatch')

    def addressed(self, key, suffix):
        digest(key)
        return self.read(self.root/(key+suffix))


def _run(files, result_path, spec, export, fixture, mode, generation):
    saved = strict_json(files.read(result_path,result=True))
    require(type(saved) is dict, 'result object required')
    require(saved['complete'] is True and type(saved['model_calls']) is int and saved['model_calls'] == 0, 'saved completion/no-model mismatch')
    script_hash = export.digest()
    equal(saved['script_sha256'],script_hash,'saved script mismatch')
    paths = saved['evidencepaths']
    require(type(paths) is list and 1 <= len(paths) <= 256 and all(type(p) is str for p in paths), 'bounded evidence paths')
    blobs = [files.read(p) for p in paths]
    def one(suffix):
        hits = [raw for p,raw in zip(paths,blobs) if p.endswith(suffix)]
        require(len(hits) == 1, 'exactly one '+suffix+' required')
        return strict_json(hits[0])
    script = files.addressed(script_hash,'.script.json')
    require(script == export.to_bytes(), 'canonical export bytes mismatch')
    require(sum(p.endswith('.script.json') for p in paths) == 1 and files.read(next(p for p in paths if p.endswith('.script.json'))) == script, 'script path mismatch')
    trace_raw = files.addressed(saved['trace_sha256'],'.trace.json')
    trace = one('.trace.json'); equal(trace,strict_json(trace_raw),'trace path mismatch')
    require(type(trace.get('schema_version')) is int and trace['schema_version'] == 1, 'trace schema')
    require(trace['complete'] is True and type(trace['model_calls']) is int and trace['model_calls'] == 0, 'trace completion/no-model mismatch')
    equal(trace['script_sha256'],script_hash,'trace script mismatch')
    target = OwnedTarget(**trace['target'])
    require(re.fullmatch(r'ReproLoop_[A-Za-z0-9_]{4,60}',target.avd_name) is not None, 'owned AVD prefix')
    require(target.generation == generation and trace['generation'] == generation and type(trace['generation']) is int, 'generation mismatch')
    equal(trace['run_id'],target.run_id,'trace run mismatch'); equal(trace['mode'],mode,'trace mode mismatch')
    build = spec.faulty_build_sha256 if mode == 'faulty' else spec.repaired_build_sha256
    equal(target.apk_sha256,build,'case APK mismatch')
    sources = trace['source_sha256']
    require(set(sources) == {'replay.py','driver.py','owned.py','app_state.py'}, 'source hash fields')
    for h in sources.values(): digest(h)
    expected = AppExpectation(target,fixture,mode)
    # Persisted reader order must contain exactly two complete five-read brackets.
    read_entries = [(i,p,raw) for i,(p,raw) in enumerate(zip(paths,blobs)) if p.endswith(('.state.json','.events.jsonl'))]
    require(len(read_entries) == 10, 'initial/final read groups required')
    snapshots = []
    for start in (0,5):
        entries = read_entries[start:start+5]
        require([Path(p).name[64:] for _,p,_ in entries] == ['.state.json','.events.jsonl','.state.json','.events.jsonl','.state.json'], 'read bracket ordering')
        raw = [b for _,_,b in entries]
        require(raw[0] == raw[2] == raw[4] and raw[1] == raw[3], 'incoherent read bracket')
        # validate_snapshot already rejects duplicate JSON and independently reconstructs events.
        snapshots.append(validate_snapshot(raw[0],raw[1],expected))
    reset, final = snapshots
    require(reset.sequence == 1 and len(reset.events) == 1 and reset.events[0].action == 'fixture_loaded' and not reset.cancel_order, 'fresh reset required')
    require((reset.target_title,reset.non_target_title) == (fixture.target_title,fixture.non_target_title), 'initial titles mismatch')
    require(final.sequence == 5 and final.explicit_cancel_flow, 'final explicit flow required')
    reset_receipt = strict_json(files.addressed(saved['reset_receipt_sha256'],'.reset.json'))
    require(type(reset_receipt.get('schema_version')) is int and reset_receipt['schema_version'] == 1, 'reset schema')
    equal(trace['reset_receipt_sha256'],saved['reset_receipt_sha256'],'trace reset mismatch')
    equal(reset_receipt['target'],asdict(target),'reset target mismatch')
    equal(reset_receipt['fixture_sha256'],fixture.sha256,'reset fixture mismatch')
    equal(reset_receipt['reset_log_sha256'],reset.log_sha256,'reset log mismatch')
    require(reset_receipt['coherent'] is True and reset_receipt['atomic'] is False, 'reset coherence claim')
    equal(reset_receipt['setup_method'],'install-r-t+pm-clear+explicit-reset','reset method')
    name(reset_receipt['host_boot_id'])
    proof = RunProof(reset,spec.task_sha256,script_hash,True,True)
    equal(saved['run_proof'],asdict(proof),'saved proof differs from raw reset')
    equal(one('.proof.json'),asdict(proof),'proof artifact differs from raw reset')
    captures = {}; observers = set(); capture_positions = []
    for pos,(p,raw) in enumerate(zip(paths,blobs)):
        if not p.endswith('.capture.json'): continue
        m = strict_json(raw)
        equal(m['target'],asdict(target),'capture target mismatch')
        equal(m['run_id'],target.run_id,'capture run mismatch'); name(m['observer']); observers.add(m['observer'])
        require(type(m['sequence']) is int and m['sequence'] > 0 and m['sequence'] not in captures, 'duplicate/bad capture sequence')
        require(pos >= 2 and paths[pos-2] == m['png_path'] and paths[pos-1] == m['xml_path'], 'capture raw path triplet mismatch')
        png,xml = files.read(m['png_path']),files.read(m['xml_path'])
        width,height = png_size(png)
        frame = Frame(target.binding,m['sequence'],png,xml,width,height,parse_hierarchy(xml,width,height))
        equal({k:m[k] for k in frame.evidence()},frame.evidence(),'capture evidence mismatch')
        captures[m['sequence']] = frame; capture_positions.append(pos)
    require(set(captures) == set(range(1,13)) and len(observers) == 1, '12 ordered captures from one observer required')
    require([strict_json(blobs[p])['sequence'] for p in capture_positions] == list(range(1,13)), 'capture order mismatch')
    require(read_entries[4][0] < min(capture_positions) and read_entries[5][0] > max(capture_positions), 'read groups must bracket actions')
    journal = one('.journal.json')
    require(set(journal) == {'actions','lab_setup','run_history'} and len(journal['actions']) == 4 and len(journal['lab_setup']) == 3 and len(journal['run_history']) == 1, 'journal scope/count mismatch')
    history = journal['run_history'][0]
    equal({k:history[k] for k in ('binding','run_id','generation','cancelled')},dict(binding=target.binding,run_id=target.run_id,generation=generation,cancelled=0),'journal history mismatch')
    require(type(history['retired']) is int and history['retired'] in (0,1),'history retired flag')
    steps = trace['steps']; require(type(steps) is list and len(steps) == 4,'four trace steps required')
    actions = {r['action_id']:r for r in journal['actions']}
    require(len(actions) == 4, 'duplicate action ID')
    requests = set()
    for index,(step,locator) in enumerate(zip(steps,export.steps)):
        require(type(step['index']) is int and step['index'] == index,'trace index')
        equal(step['locator'],asdict(locator),'trace selector mismatch')
        pre,current,post = (captures[index*3+j] for j in (1,2,3))
        require(pre.png == current.png and pre.xml == current.xml,'fresh driver precheck mismatch')
        equal(step['pre'],pre.evidence(),'trace pre evidence mismatch')
        require(phase(pre) == locator.expected_screen,'pre visible phase mismatch')
        x,y = current.resolve(locator.resource_id,locator.visible_text)
        receipt = step['receipt']; require(receipt['state'] == 'ACCEPTED','trace action not accepted')
        equal(receipt['evidence'],post.evidence(),'trace post mismatch')
        row = actions[receipt['action_id']]
        equal({k:row[k] for k in ('binding','owner','generation','state','preframe')},dict(binding=target.binding,owner=target.owner_id,generation=generation,state='ACCEPTED',preframe=pre.evidence_sha256),'action journal identity/state mismatch')
        payload = strict_json(row['payload'].encode())
        want = dict(action_id=row['action_id'],request_id=row['request_id'],kind='tap',preframe_hash=pre.evidence_sha256,resource_id=locator.resource_id,text=locator.visible_text,wait_seconds=0)
        # Parent optional pixel API is permitted only as None for no-model replay.
        if 'x' in payload or 'y' in payload: want.update(x=None,y=None)
        equal(payload,want,'action payload mismatch')
        require(row['request_id'] not in requests,'duplicate request ID'); requests.add(row['request_id'])
        equal(strict_json(row['planned_args'].encode()),['shell','input','tap',str(x),str(y)],'planned input differs from unique current center')
        equal(strict_json(row['evidence'].encode()),post.evidence(),'journal post mismatch')
        if index in (0,3): require(phase(post) == 'selected' and visible(post,'rename_open','Rename'),'post selected predicate')
        elif index == 1: require(phase(post) == 'rename' and visible(post,'preset_today','Today') and visible(post,'cancel_edit','Cancel'),'post rename predicate')
        else: require(phase(post) == 'rename' and any(n.text == 'Draft: Today' for n in post.nodes),'post draft predicate')
    setups = {r['id']:r for r in journal['lab_setup']}
    require(len(setups) == 3,'duplicate setup ID')
    for index in range(3):
        row = setups[target.binding+':'+str(index)]
        require(row['binding'] == target.binding and row['state'] == 'ACCEPTED','setup not accepted/bound')
        args = strict_json(row['payload'].encode())
        if index == 0:
            require(type(args) is list and len(args) == 4 and args[:3] == ['install','-r','-t'] and type(args[3]) is str and Path(args[3]).is_absolute() and Path(args[3]).name == 'pockettasks-'+mode+'-debug.apk','setup install argv')
            # APK path is metadata only: NEVER fetch files outside evidence root.
        elif index == 1: equal(args,['shell','pm','clear',PACKAGE],'setup clear argv')
        else:
            equal(args,['shell','am','start','-W','-n',PACKAGE+'/.MainActivity','--ez','reset_fixture','true','--es','fixture_id',fixture.fixture_id,'--es','run_id',target.run_id,'--el','generation',str(generation),'--ei','seed',str(fixture.seed),'--es','layout_variant',fixture.layout_variant,'--es','target_title',fixture.target_title,'--es','non_target_title',fixture.non_target_title,'--es','expected_fixture_sha256',fixture.sha256],'setup reset argv')
    observation = AppObservation('COHERENT',final,(),True)
    computed = OracleRun(**oracle_fields(spec,observation,proof))
    require(computed.completed and computed.goal_reached,'computed oracle incomplete')
    equal(saved['oracle_run'],asdict(computed),'saved oracle differs from raw computed oracle')
    return computed,dict(target=asdict(target),reset_sha256=saved['reset_receipt_sha256'],reset_log_sha256=reset.log_sha256,final_log_sha256=final.log_sha256,trace_sha256=saved['trace_sha256'],source_sha256=sources,host_boot_id=reset_receipt['host_boot_id'],observer=next(iter(observers)))


def bind_saved_pair(spec: CaseSpec, export: SemanticExport, fixture: FixtureSpec,
                    faulty_result_path: Path, fixed_result_path: Path,
                    evidence_root: Path, generation: int = 1,
                    original_evidence_root: Path | None = None) -> BindingReport:
    proof = {'basis':'bounded raw byte links and trusted host origin assumption; NOT native or producer attestation',
             'limits':['capture/read coherence is not atomic','source hash agreement is not a full source snapshot','saved journal producer authenticity is outside this validator']}
    try:
        validate_spec(spec)
        require(type(export) is SemanticExport and type(fixture) is FixtureSpec,'typed export/fixture required')
        require(type(generation) is int and 1 <= generation <= 2147483647,'generation bound')
        require(spec.faulty_build_sha256 != spec.repaired_build_sha256,'distinct APKs required')
        require(export.package == PACKAGE and export.task_sha256 == spec.task_sha256 and export.fixture_sha256 == spec.fixture_sha256 == fixture.sha256,'case/export/fixture mismatch')
        required = [('task_target','Target task: '+fixture.target_title,'tasks'),('rename_open','Rename','selected'),('preset_today','Today','rename'),('cancel_edit','Cancel','rename')]
        equal([asdict(x) for x in export.steps],[dict(resource_id=PACKAGE+':id/'+r,visible_text=t,expected_screen=s) for r,t,s in required],'immutable four-selector workflow required')
        export.to_bytes()
        files = Files(evidence_root, original_evidence_root)
        faulty,fp = _run(files,faulty_result_path,spec,export,fixture,'faulty',generation)
        fixed,rp = _run(files,fixed_result_path,spec,export,fixture,'fixed',generation)
        for key in ('serial','avd_name','owner_id','boot_id','package'):
            equal(fp['target'][key],rp['target'][key],'pair owner/boot identity mismatch')
        for key in ('source_sha256','host_boot_id'):
            equal(fp[key],rp[key],'pair source/host mismatch')
        require(faulty.run_id != fixed.run_id and fp['observer'] != rp['observer'],'independent run/observer required')
        for key in ('reset_sha256','reset_log_sha256','final_log_sha256','trace_sha256'):
            require(fp[key] != rp[key],'shared pair '+key)
        collected = collect_pair(spec,faulty,fixed,generation,export_created=True,pair_binding_valid=True)
        proof.update(script_sha256=export.digest(),faulty=fp,fixed=rp,bytes_checked=files.total,files_checked=len(files.cache))
        return BindingReport(True,'raw saved pair links validated; host origin remains assumed',collected,proof)
    except (ValueError,TypeError,KeyError,IndexError,OSError,RuntimeError,RecursionError,OverflowError) as error:
        return BindingReport(False,type(error).__name__+': '+str(error),None,proof)
