"""Pure-processing observations of caller-supplied, uniformly decoded owned video.

No sampling, action inference, network, decoder execution or device operations.
"""
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
import base64
import io
import json
import math
import os
import re
import stat
from .runtime.owned import png_size

MAX_PNG = 8 * 1024 * 1024


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _hash(value):
    _require(type(value) is str and re.fullmatch(r'[a-f0-9]{64}',value), 'SHA256 required')
    return value


def _seconds(value):
    _require(type(value) in (int,float) and math.isfinite(value) and value >= 0,
             'finite nonboolean decoded seconds required')
    return value


def _read(path, maximum):
    """Canonical absolute paths; descriptor-relative no-follow component walk."""
    p = Path(path)
    _require(p.is_absolute() and '..' not in p.parts and str(p) == str(path),
             'canonical absolute local path required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in p.parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd); fd = nxt
        source = os.open(p.name,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,dir_fd=fd)
    finally:
        os.close(fd)
    try:
        info = os.fstat(source)
        _require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,'regular file byte bound')
        with os.fdopen(source,'rb',closefd=False) as stream:
            raw = stream.read(maximum+1)
        _require(len(raw) == info.st_size,'file size changed')
        return raw
    finally:
        os.close(source)


def _json(raw):
    def pairs(items):
        result = {}
        for key,value in items:
            _require(key not in result,'duplicate JSON field')
            result[key] = value
        return result
    return json.loads(raw,object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def _red_candidate(raw, png_hash):
    try:
        import PIL
        from PIL import Image
    except ImportError as error:
        raise ImportError('native_marker_candidates requires optional Pillow==13.0.0; no fallback') from error
    _require(PIL.__version__ == '13.0.0','native marker detector requires Pillow==13.0.0')
    with Image.open(io.BytesIO(raw)) as source:
        rgb = source.convert('RGB')
        _require(rgb.size == (720,1280),'fixed synthetic frame dimensions required')
        pixels = set()
        for index,(r,g,b) in enumerate(rgb.get_flattened_data()):
            y,x = divmod(index,720)
            if y >= 32 and r >= 100 and r-g >= 70 and r-b >= 70:
                pixels.add((x,y))
                if len(pixels) > 64:
                    return None,'AMBIGUOUS'
    if not pixels:
        return None,'ABSENT'
    remaining = set(pixels); components = []
    while remaining:
        todo = [remaining.pop()]; component = set(todo)
        while todo:
            x,y = todo.pop()
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    point = (x+dx,y+dy)
                    if point in remaining:
                        remaining.remove(point);component.add(point);todo.append(point)
        components.append(component)
    if len(components) != 1 or len(pixels) > 16:
        return None,'AMBIGUOUS'
    xs,ys = zip(*pixels); bounds = [min(xs),min(ys),max(xs),max(ys)]
    if bounds[2]-bounds[0]+1 > 4 or bounds[3]-bounds[1]+1 > 4:
        return None,'AMBIGUOUS'
    return {'red_marker_candidate':{'bounds':bounds,
            'center':[sum(xs)//len(xs),sum(ys)//len(ys)],
            'source_png_sha256':png_hash}},'CANDIDATE'


@dataclass(frozen=True)
class FrameObservation:
    timestamp_ms: int
    png_sha256: str
    width: int
    height: int
    source_media_sha256: str
    data_url: str = field(repr=False)
    pointer_candidate: dict | None
    pointer_status: str
    ocr_regions: tuple = ()
    prior_pointer_text_candidates: tuple = ()
    pointer_location_changed: bool | None = None
    ocr_observer: str | None = None

    def observer_summary(self):
        """Visible-pixel representation only; no goal, labels or action claims."""
        summary = dict(decoded_timestamp_ms=self.timestamp_ms,
            pointer_status=self.pointer_status,pointer_candidate=self.pointer_candidate,
            notice='UNTRUSTED SAME-VIDEO PIXEL OBSERVATION. NotAuthorization; not touch attestation or action authority.')
        if self.ocr_observer is not None:
            summary.update(ocr_observer=self.ocr_observer,ocr_regions=self.ocr_regions,
                           pointer_location_changed=self.pointer_location_changed,
                           previous_visible_text_candidates=self.prior_pointer_text_candidates)
        return json.dumps(summary,separators=(',',':'),ensure_ascii=True)

    def response_items(self):
        return [{'type':'input_text','text':self.observer_summary()},
                {'type':'input_image','image_url':self.data_url,'detail':'high'}]


def build_frame_observations(decoder_json_path, expected_media_sha256, *,
                             native_marker_candidates: bool = False) -> tuple[FrameObservation,...]:
    _hash(expected_media_sha256)
    _require(type(native_marker_candidates) is bool,'boolean marker option required')
    path = Path(decoder_json_path)
    value = _json(_read(decoder_json_path,64*1024))
    root_fields = {'schema_version','decoder','media_sha256','video_tracks','audio_tracks',
                   'duration_seconds','frames','attestation','coverage_judgment'}
    _require(type(value) is dict and set(value) == root_fields,'unsupported decoder fields/source paths')
    _require(type(value['schema_version']) is int and value['schema_version'] == 1
             and value['decoder'] == 'macOS AVFoundation','verified decoder contract required')
    _require(value['media_sha256'] == expected_media_sha256,'source media SHA mismatch')
    _require(type(value['video_tracks']) is int and value['video_tracks'] == 1
             and type(value['audio_tracks']) is int and value['audio_tracks'] == 0,'one video / no audio required')
    duration = _seconds(value['duration_seconds'])
    _require(0 < duration <= 45 and value['attestation'] is False
             and value['coverage_judgment'] == 'REQUIRES_HUMAN_INSPECTION','duration/coverage contract')
    rows = value['frames']
    _require(type(rows) is list and 1 <= len(rows) <= 16,'frame count bound')
    result = []; previous_seconds = -1; previous_ms = -1; previous_hash = None
    for row in rows:
        _require(type(row) is dict and set(row) == {'file','sha256','width','height','requested_seconds','decoded_seconds'},
                 'unsupported frame fields/source paths')
        filename = row['file']
        _require(type(filename) is str and re.fullmatch(r'frame-[0-9]{2}\.png',filename),'flat frame filename required')
        image_hash = _hash(row['sha256'])
        actual = _seconds(row['decoded_seconds']); _seconds(row['requested_seconds'])
        _require(actual <= duration,'frame outside video duration')
        stamp = math.floor(actual*1000)
        _require(type(row['width']) is int and type(row['height']) is int
                 and (row['width'],row['height']) == (720,1280),'decoder dimensions mismatch')
        raw = _read(str(path.parent/filename),MAX_PNG)
        _require(sha256(raw).hexdigest() == image_hash,'PNG SHA mismatch')
        _require(png_size(raw) == (720,1280),'strict native PNG dimensions mismatch')
        if actual == previous_seconds:
            _require(image_hash == previous_hash,'duplicate actual timestamp with differing PNG')
            continue
        _require(actual > previous_seconds and stamp > previous_ms,'timestamps must strictly increase')
        candidate,status = _red_candidate(raw,image_hash) if native_marker_candidates else (None,'NOT_REQUESTED')
        result.append(FrameObservation(stamp,image_hash,720,1280,expected_media_sha256,
                      'data:image/png;base64,'+base64.b64encode(raw).decode('ascii'),candidate,status))
        previous_seconds,previous_ms,previous_hash = actual,stamp,image_hash
    return tuple(result)


def with_ocr_context(observations: tuple, ocr_json_path, expected_media_sha) -> tuple[FrameObservation,...]:
    """All OCR regions, plus exact prior-frame overlap at changed red candidates.

    Geometry only: no nearest region, semantic filtering or action inference.
    """
    _hash(expected_media_sha)
    _require(type(observations) is tuple and 1 <= len(observations) <= 16,'observation tuple bound')
    value = _json(_read(ocr_json_path,1024*1024))
    _require(type(value) is dict and set(value) == {'schema_version','decoder','media_sha256',
             'tool_source_sha256','attestation','frames'},'OCR root fields')
    _require(type(value['schema_version']) is int and value['schema_version'] == 1
             and value['decoder'] == 'macOS Vision' and value['attestation'] is False,'OCR observer contract')
    _require(value['media_sha256'] == expected_media_sha,'OCR media mismatch')
    _hash(value['tool_source_sha256'])
    rows = value['frames']
    _require(type(rows) is list and len(rows) == len(observations),'OCR frame count mismatch')
    result = []; prior_point = None; prior_regions = (); prior_frame = None; prior_stamp = -1
    for frame,row in zip(observations,rows):
        _require(type(frame) is FrameObservation and frame.source_media_sha256 == expected_media_sha
                 and (frame.width,frame.height) == (720,1280),'observation source/dimensions')
        _hash(frame.png_sha256)
        _require(type(frame.timestamp_ms) is int and prior_stamp < frame.timestamp_ms <= 45000,'observation timestamp order')
        _require(type(row) is dict and set(row) == {'png_sha256','timestamp_ms','regions'},'OCR frame fields')
        _require(row['png_sha256'] == frame.png_sha256 and type(row['timestamp_ms']) is int
                 and row['timestamp_ms'] == frame.timestamp_ms,'OCR PNG/timestamp mismatch')
        regions = row['regions']
        _require(type(regions) is list and len(regions) <= 64,'OCR region count bound')
        validated = []
        for region in regions:
            _require(type(region) is dict and set(region) == {'text','confidence','bounds'},'OCR region fields')
            text,confidence,bounds = region['text'],region['confidence'],region['bounds']
            _require(type(text) is str and 1 <= len(text) <= 256
                     and all(c.isprintable() for c in text),'OCR printable text bound')
            _require(type(confidence) in (int,float) and math.isfinite(confidence)
                     and 0 <= confidence <= 1,'OCR confidence bound')
            _require(type(bounds) is list and len(bounds) == 4 and all(type(n) is int for n in bounds)
                     and 0 <= bounds[0] < bounds[2] <= 720 and 0 <= bounds[1] < bounds[3] <= 1280,'OCR integer bounds')
            validated.append(dict(text=text,confidence=confidence,bounds=list(bounds)))
        point = None; changed = None; matches = []
        if frame.pointer_candidate is not None:
            _require(frame.pointer_status == 'CANDIDATE' and type(frame.pointer_candidate) is dict
                     and set(frame.pointer_candidate) == {'red_marker_candidate'},'pointer candidate fields')
            candidate = frame.pointer_candidate['red_marker_candidate']
            _require(type(candidate) is dict and set(candidate) == {'center','bounds','source_png_sha256'}
                     and candidate['source_png_sha256'] == frame.png_sha256,'pointer source mismatch')
            center = candidate['center']
            _require(type(center) is list and len(center) == 2 and all(type(n) is int for n in center)
                     and 0 <= center[0] < 720 and 0 <= center[1] < 1280,'pointer center bounds')
            point = tuple(center)
            changed = prior_point is None or max(abs(a-b) for a,b in zip(point,prior_point)) > 3
            if changed and prior_frame is not None:
                for region in prior_regions:
                    l,t,r,b = region['bounds']
                    if region['confidence'] >= 0.7 and l <= point[0] < r and t <= point[1] < b:
                        matches.append(dict(region,source_png_sha256=prior_frame.png_sha256,
                                            timestamp_ms=prior_frame.timestamp_ms))
            prior_point = point
        else:
            _require(frame.pointer_status in ('ABSENT','AMBIGUOUS','NOT_REQUESTED'),'pointer status mismatch')
        result.append(replace(frame,ocr_regions=tuple(validated),
                      prior_pointer_text_candidates=tuple(matches),pointer_location_changed=changed,
                      ocr_observer='macOS Vision'))
        prior_regions,prior_frame,prior_stamp = tuple(validated),frame,frame.timestamp_ms
    return tuple(result)

def _context_label(value):
    """Whitespace/case normalization only; never synonyms or fuzzy matching."""
    return ' '.join(value.split()).casefold()


def _context_point(frame):
    """Validate the inclusive pixel bounds emitted by _red_candidate."""
    candidate = frame.pointer_candidate
    if candidate is None:
        _require(type(frame.pointer_status) is str and frame.pointer_status in
                 ('ABSENT', 'AMBIGUOUS', 'NOT_REQUESTED'), 'pointer status mismatch')
        return None
    _require(frame.pointer_status == 'CANDIDATE' and type(candidate) is dict
             and set(candidate) == {'red_marker_candidate'}, 'pointer candidate fields')
    marker = candidate['red_marker_candidate']
    _require(type(marker) is dict and set(marker) ==
             {'center', 'bounds', 'source_png_sha256'}, 'pointer marker fields')
    _hash(marker['source_png_sha256'])
    _require(marker['source_png_sha256'] == frame.png_sha256, 'pointer source mismatch')
    center, bounds = marker['center'], marker['bounds']
    _require(type(center) is list and len(center) == 2
             and all(type(n) is int for n in center), 'pointer integer center')
    _require(type(bounds) is list and len(bounds) == 4
             and all(type(n) is int for n in bounds), 'pointer integer bounds')
    l, t, r, b = bounds
    _require(0 <= l <= center[0] <= r < 720 and 32 <= t <= center[1] <= b < 1280
             and r-l < 4 and b-t < 4, 'compact native pointer bounds')
    return tuple(center)


def _context_regions(frame):
    """Validate all OCR, including ignored overlay and low-confidence regions."""
    _require(frame.ocr_observer == 'macOS Vision', 'same-frame Vision OCR required')
    regions = frame.ocr_regions
    _require(type(regions) is tuple and len(regions) <= 64, 'OCR region tuple bound')
    visible = []
    for region in regions:
        _require(type(region) is dict and set(region) == {'text', 'confidence', 'bounds'},
                 'OCR region fields')
        text, confidence, bounds = region['text'], region['confidence'], region['bounds']
        _require(type(text) is str and 1 <= len(text) <= 256
                 and all(c.isprintable() for c in text), 'OCR printable text bound')
        _require(type(confidence) in (int, float) and 0 <= confidence <= 1
                 and math.isfinite(confidence), 'OCR confidence bound')
        _require(type(bounds) is list and len(bounds) == 4
                 and all(type(n) is int for n in bounds), 'OCR integer bounds')
        l, t, r, b = bounds
        _require(0 <= l < r <= 720 and 0 <= t < b <= 1280, 'OCR bounds')
        if confidence >= 0.7 and b > 32:
            visible.append((_context_label(text), (l, t, r, b)))
    return visible


def validate_temporal_ocr_candidate_labels(initial_target_title, preset_label, actions, frames) -> dict:
    """Pure sampled-scene agreement, NOT a tap detector or physical attestation.

    Inputs must be observations already bound to the same PNG/media by the
    existing builder and OCR loader. No image decoding or source re-reading is
    performed here. Action times name supplied after-transition frames, never
    touch instants. Adjacent actual timestamps need not be uniformly spaced.
    """
    for label in (initial_target_title, preset_label):
        _require(type(label) is str and 1 <= len(label) <= 64
                 and label == label.strip()
                 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 .:_-]*', label),
                 'unsupported untrusted label')
    operations = ('select_target', 'open_rename', 'choose_preset', 'cancel_edit')
    expected = tuple(map(_context_label,
                         ('Target task: '+initial_target_title, 'Rename', preset_label, 'Cancel')))
    _require(type(actions) is tuple and len(actions) == 4, 'four action tuple required')
    previous = -1
    for action, operation in zip(actions, operations):
        _require(type(action) is dict and set(action) == {'operation', 'timestamp_ms'},
                 'action fields')
        stamp = action['timestamp_ms']
        _require(type(action['operation']) is str and action['operation'] == operation
                 and type(stamp) is int and previous < stamp <= 45000,
                 'unsupported operation sequence/timestamp')
        previous = stamp
    _require(type(frames) is tuple and 1 <= len(frames) <= 16, 'frame tuple bound')
    source = None; previous = -1; points = []; regions = []; indexes = {}
    for index, frame in enumerate(frames):
        _require(type(frame) is FrameObservation, 'actual FrameObservation required')
        _hash(frame.source_media_sha256); _hash(frame.png_sha256)
        if source is None:
            source = frame.source_media_sha256
        _require(frame.source_media_sha256 == source and type(frame.width) is int
                 and type(frame.height) is int and (frame.width, frame.height) == (720, 1280),
                 'same media and native dimensions required')
        _require(type(frame.timestamp_ms) is int and previous < frame.timestamp_ms <= 45000,
                 'strict integer actual timestamp order')
        previous = frame.timestamp_ms
        indexes[frame.timestamp_ms] = index
        points.append(_context_point(frame))
        regions.append(_context_regions(frame))
    matches = []
    for action, label in zip(actions, expected):
        index = indexes.get(action['timestamp_ms'])
        _require(index is not None and index > 0, 'exact supplied after-frame timestamp required')
        before, after = frames[index-1], frames[index]
        point = points[index]
        _require(point is not None, 'single current pixel-derived pointer required')
        texts = {text for text, (l, t, r, b) in regions[index-1]
                 if l <= point[0] < r and t <= point[1] < b}
        _require(len(texts) == 1 and label in texts, 'unique exact prior OCR label required')
        before_signature = sorted({text for text, _ in regions[index-1]})
        after_signature = sorted({text for text, _ in regions[index]})
        _require(before_signature != after_signature, 'visible scene text must change')
        prior_point = points[index-1]
        stationary = None if prior_point is None else max(
            abs(a-b) for a, b in zip(point, prior_point)) <= 3
        matches.append(dict(operation=action['operation'], normalized_label=label,
            before_timestamp_ms=before.timestamp_ms, after_timestamp_ms=after.timestamp_ms,
            before_png_sha256=before.png_sha256, after_png_sha256=after.png_sha256,
            pointer_center=list(point), stationary_or_small_move=stationary))
    return dict(type='SAMPLED_PRIOR_OCR_POINT_SCENE_AGREEMENT_V4', matched_labels=4,
        attestation=False, source_media_sha256=source, matches=matches,
        assumptions=[
            'Source-controlled static tap-only event-driven 720x1280 producer; native overlay occupies top32 pixels.',
            'Caller used the existing same-PNG/media builder and OCR loader; source bytes are not reverified here.',
        ], limits=[
            'Labels and sampled scene consistency only, not causal tap, physical input, OS or timing proof.',
            'Timestamps identify first supplied after-transition frames, not touch instants; previous frame is adjacent actual decoded sample.',
            'Persistent or stationary points are allowed; OCR errors, jitter and unsampled transitions remain possible.',
            'Generic scene text changes do not establish a particular after-state or correct application behavior.',
        ])
