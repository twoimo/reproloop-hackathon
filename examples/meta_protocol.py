"""Source-grounded request builders/validators. No network or device execution.

Docs observed 2026-10-27: dev.meta.ai/docs/{computer-use,structured-output,
video-understanding,tool-calling,pricing-rate-limits,models}.
These checks are application policy, not a guarantee of provider billing/safety.
"""
from __future__ import annotations
import base64
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from threading import Lock

MODEL = 'muse-spark-1.3'  # Standard, not Contributor; no Wonder in South Korea.


def _nonempty_text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('invalid bounded text')
    return value


def strict_result_schema() -> dict:
    # Schema conformance never proves factual correctness or authorization.
    return {'type': 'object', 'properties': {
        'status': {'type': 'string', 'enum': ['candidate', 'uncertain']},
        'summary': {'type': 'string'},
        'evidence_ids': {'type': 'array', 'items': {'type': 'string'}},
    }, 'required': ['status', 'summary', 'evidence_ids'], 'additionalProperties': False}


def video_request(file_id: str, prompt: str, max_output_tokens: int = 4096) -> dict:
    _nonempty_text(file_id, 200); _nonempty_text(prompt, 12000)
    if not file_id.startswith('file-'):
        raise ValueError('expected already uploaded Files API id')
    if type(max_output_tokens) is not int or not 256 <= max_output_tokens <= 8192:
        raise ValueError('invalid output-token budget')
    return {'model': MODEL, 'store': False, 'max_output_tokens': max_output_tokens,
        'input': [{'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': prompt},
            {'type': 'input_file', 'file_id': file_id}]}],
        # Responses uses text.format, NOT Chat Completions response_format.
        'text': {'format': {'type': 'json_schema', 'name': 'EvidenceCandidate',
            'strict': True, 'schema': strict_result_schema()}}}


def computer_initial_request(png: bytes, task: str) -> dict:
    _nonempty_text(task, 12000)
    if not isinstance(png, bytes) or not png.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('expected PNG bytes, not mismatched MIME')
    if len(png) > 25 * 1024 * 1024:
        raise ValueError('image exceeds provider decoded-byte limit')
    # PNG header is only a format precheck. Decode/validate image off the API path
    # before using coordinates; this function deliberately does not execute it.
    return {'model': MODEL, 'store': False, 'max_output_tokens': 4096,
        'tools': [{'type': 'computer'}],
        'input': [{'role': 'user', 'content': [
            {'type': 'input_text', 'text': task},
            {'type': 'input_image', 'image_url': 'data:image/png;base64,' +
                base64.b64encode(png).decode('ascii')}]}]}


@dataclass(frozen=True)
class FrameBinding:
    digest: str
    width: int
    height: int
    generation: int


def validate_computer_call(call: dict, frame: FrameBinding, current: FrameBinding) -> tuple[dict, ...]:
    """Deliberately narrow MVP policy: click/screenshot/wait only, no execution.

    Returned actions are SYNTAX-ONLY proposals, never dispatch permission.
    Pending safety checks block, not auto-acknowledge. In a production batch,
    driver must recapture/revalidate after navigation or modal transitions.
    """
    # Validate BOTH sides before dataclass equality: True == 1 is not identity.
    for bound in (frame, current):
        if type(bound) is not FrameBinding:
            raise ValueError('typed FrameBinding required')
        if (type(bound.digest) is not str or len(bound.digest)!=64 or
            any(c not in '0123456789abcdef' for c in bound.digest) or
            type(bound.generation) is not int or not 1 <= bound.generation <= 2**63-1 or
            any(type(v) is not int or not 1 <= v <= 16384 for v in (bound.width,bound.height))):
            raise ValueError('invalid frame digest/generation/dimensions')
    if frame != current:
        raise ValueError('stale frame or cancelled generation')
    if not isinstance(call, dict) or call.get('type') != 'computer_call' or call.get('status') != 'completed':
        raise ValueError('incomplete or wrong protocol item')
    cid=call.get('call_id')
    if type(cid) is not str or not 1 <= len(cid) <= 64 or not cid.strip() or cid!=cid.strip():
        raise ValueError('invalid call_id')
    checks=call.get('pending_safety_checks')
    if not isinstance(checks, list) or checks:
        raise ValueError('missing or unresolved safety checks')
    actions=call.get('actions')
    if not isinstance(actions, list) or not 1 <= len(actions) <= 4:
        raise ValueError('invalid action batch')
    result=[]
    for action in actions:
        if not isinstance(action, dict): raise ValueError('invalid action')
        kind=action.get('type')
        if not isinstance(kind,str): raise ValueError('invalid action type')
        if kind=='click':
            if set(action)!={'type','button','x','y'} or action['button']!='left':
                raise ValueError('unsupported click')
            x,y=action['x'],action['y']
            # bool is an int in Python; explicitly reject booleans and NaN/Inf.
            if any(type(v) not in (int,float) or (type(v) is float and not math.isfinite(v)) for v in (x,y)):
                raise ValueError('invalid pixel coordinate')
            if any(type(v) is float and not v.is_integer() for v in (x,y)):
                raise ValueError('fractional MVP pixels not allowed')
            if not (0 <= x < frame.width and 0 <= y < frame.height):
                raise ValueError('pixel outside exact prior screenshot')
        elif kind in {'wait','screenshot'}:
            if set(action)!={'type'}: raise ValueError('unknown action fields')
        else:
            raise ValueError('action not enabled by this MVP executor')
        proposal=dict(action)
        if kind=='click':proposal.update(x=int(x),y=int(y))
        result.append(proposal)
    return tuple(result)


def parse_candidate(text: str) -> dict:
    """Local validation even when provider structured decoding is used."""
    _nonempty_text(text, 20000)
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    try:
        obj=json.loads(text, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except RecursionError as exc:
        raise ValueError('JSON nesting exceeds parser budget') from exc
    if not isinstance(obj,dict) or set(obj)!={'status','summary','evidence_ids'}:
        raise ValueError('invalid candidate fields')
    if not isinstance(obj['status'],str) or obj['status'] not in {'candidate','uncertain'}: raise ValueError('invalid status')
    _nonempty_text(obj['summary'],4000)
    ids=obj['evidence_ids']
    if not isinstance(ids,list) or len(ids)>32 or any(type(x) is not str or not x.strip() or x!=x.strip() or len(x)>120 for x in ids):
        raise ValueError('invalid evidence ids')
    return obj


def estimate_usd(input_tokens: int, cached_tokens: int, output_tokens: int) -> Decimal:
    vals=(input_tokens,cached_tokens,output_tokens)
    if any(type(v) is not int or v<0 for v in vals) or cached_tokens>input_tokens:
        raise ValueError('invalid measured token counts')
    return (Decimal(input_tokens-cached_tokens)*Decimal('1.25') +
            Decimal(cached_tokens)*Decimal('0.15') +
            Decimal(output_tokens)*Decimal('4.25'))/Decimal(1000000)


class CreditAdmission:
    """In-process admission only, not a payment-provider spending cap.

    estimate_upper must be a justified per-call upper bound. Actual billed cost
    may differ; caller must record usage, stop on ambiguity and reconcile. State
    is NOT durable: process crash/restart must not reset a production ledger.
    """
    def __init__(self, grant_verified: bool=False, local_limit: Decimal=Decimal('0')):
        if type(grant_verified) is not bool or not isinstance(local_limit,Decimal) or not local_limit.is_finite() or local_limit<0:
            raise ValueError('invalid credit admission configuration')
        self.verified=grant_verified; self.limit=local_limit
        self.reserved=Decimal('0'); self._lock=Lock(); self._ids={}

    def reserve(self, request_id: str, payload: dict, estimate_upper: Decimal) -> bool:
        _nonempty_text(request_id,120)
        if not isinstance(estimate_upper,Decimal) or not estimate_upper.is_finite() or estimate_upper<=0:
            raise ValueError('invalid conservative cost reservation')
        if not isinstance(payload,dict): raise ValueError('payload must be an object')
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        with self._lock:
            old=self._ids.get(request_id)
            if old is not None:
                if old!=(digest,estimate_upper): raise ValueError('request id conflict')
                return False  # Already admitted; MUST NOT send again.
            if not self.verified: raise PermissionError('free credit grant unverified; network denied')
            if self.reserved+estimate_upper>self.limit: raise PermissionError('local cost budget exhausted')
            self._ids[request_id]=(digest,estimate_upper); self.reserved+=estimate_upper
            return True
