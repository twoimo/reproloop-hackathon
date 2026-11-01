"""Narrow, injected ADB boundary. No subprocess implementation is supplied."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import math
import re
import struct
import zlib
import xml.etree.ElementTree as ET
from typing import Protocol

PACKAGE = 'com.tinyburn.reproloop.lab'

class RuntimeStop(RuntimeError):
    pass


def name(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise ValueError('invalid identity')
    return value


def digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('invalid digest')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError('invalid finite number')
    return value


def png_size(png):
    if len(png) < 33 or png[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeStop('invalid PNG')
    offset, chunks, compressed = 8, [], bytearray()
    while offset < len(png):
        if len(chunks) >= 4096 or offset + 12 > len(png):
            raise RuntimeStop('PNG chunk bound')
        size = struct.unpack('>I',png[offset:offset+4])[0]
        kind = png[offset+4:offset+8]
        if not re.fullmatch(b'[A-Za-z]{4}',kind) or kind[2] & 32:
            raise RuntimeStop('PNG chunk type')
        if not kind[0] & 32 and kind not in (b'IHDR',b'PLTE',b'IDAT',b'IEND'):
            raise RuntimeStop('unsupported PNG critical chunk')
        if not chunks and kind != b'IHDR':
            raise RuntimeStop('PNG IHDR first')
        end = offset + 12 + size
        if end > len(png):
            raise RuntimeStop('truncated PNG')
        data = png[offset+8:offset+8+size]
        crc = struct.unpack('>I',png[offset+8+size:end])[0]
        if zlib.crc32(kind+data) != crc:
            raise RuntimeStop('PNG CRC')
        chunks.append(kind)
        if kind == b'IHDR':
            if len(chunks) != 1 or size != 13:
                raise RuntimeStop('PNG IHDR')
            w,h,depth,color,compression,filtering,interlace = struct.unpack('>IIBBBBB',data)
            if not (1 <= w <= 16384 and 1 <= h <= 16384) or depth != 8 or color not in (0,2,6) or (compression,filtering,interlace) != (0,0,0):
                raise RuntimeStop('unsupported bounded PNG')
        elif kind == b'PLTE':
            if chunks.count(b'PLTE') != 1 or b'IDAT' in chunks or color == 0 or not 3 <= size <= 768 or size % 3:
                raise RuntimeStop('PNG palette')
        elif kind == b'IDAT':
            if b'IDAT' in chunks[:-1] and chunks[-2] != b'IDAT':
                raise RuntimeStop('PNG noncontiguous IDAT')
            compressed.extend(data)
        elif kind == b'IEND':
            if size or end != len(png):
                raise RuntimeStop('PNG trailing bytes')
        offset = end
    if not chunks or chunks[0] != b'IHDR' or chunks[-1] != b'IEND' or not compressed:
        raise RuntimeStop('incomplete PNG')
    expected = h * (1 + w * {0:1,2:3,6:4}[color])
    if expected > 64 * 1024 * 1024:
        raise RuntimeStop('PNG decoded bound')
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected+1)
        if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise RuntimeStop('PNG decoded length')
        stride = expected // h
        if any(raw[i] > 4 for i in range(0,expected,stride)):
            raise RuntimeStop('PNG filter')
    except zlib.error as error:
        raise RuntimeStop('invalid PNG compression') from error
    return w,h


@dataclass(frozen=True)
class OwnedTarget:
    serial: str
    avd_name: str
    owner_id: str  # minted by parent when creating this AVD, NOT inferred from AVD name
    boot_id: str
    apk_sha256: str
    run_id: str
    generation: int
    package: str = PACKAGE

    def __post_init__(self):
        for x in (self.avd_name, self.owner_id, self.boot_id, self.run_id):
            name(x)
        if not re.fullmatch(r'emulator-[0-9]{4,6}', self.serial):
            raise ValueError('emulator serial required')
        digest(self.apk_sha256)
        if self.package != PACKAGE or type(self.generation) is not int or not 1 <= self.generation < 2**63:
            raise ValueError('invalid package/generation')

    @property
    def binding(self):
        return sha256(repr(self).encode()).hexdigest()


@dataclass(frozen=True)
class CommandResult:
    code: int
    stdout: bytes
    stderr: bytes = b''


class CmdRunner(Protocol):
    def __call__(self, argv: tuple[str, ...], timeout: float, max_output: int) -> CommandResult: ...


@dataclass(frozen=True)
class Node:
    resource_id: str
    text: str
    clickable: bool
    bounds: tuple[int, int, int, int]


def parse_hierarchy(xml: bytes, width: int, height: int) -> tuple[Node, ...]:
    if len(xml) > 1_048_576 or b'<!' in xml or b'\x00' in xml:
        raise RuntimeStop('unsafe XML')
    try:
        root = ET.fromstring(xml)
        if root.tag != 'hierarchy':
            raise ValueError('wrong root')
        nodes = []
        stack = [(root, 0)]
        count = 0
        while stack:
            element, depth = stack.pop()
            count += 1
            if count > 4096 or depth > 64:
                raise ValueError('hierarchy bounds')
            stack.extend((child, depth + 1) for child in element)
            if element.tag == 'hierarchy':
                continue
            if element.tag != 'node' or element.get('package') != PACKAGE:
                raise ValueError('foreign node/package')
            rid, text = element.get('resource-id', ''), element.get('text', '')
            # Observed framework-owned, noninteractive Activity/Dialog wrapper.
            # It is retained in raw evidence but is NEVER a semantic selector.
            if rid == 'android:id/content' and element.get('class') == 'android.widget.FrameLayout' and element.get('clickable') == 'false':
                rid = ''
            if len(text) > 4096 or (rid and not rid.startswith(PACKAGE + ':id/')):
                raise ValueError('invalid node identity')
            match = re.fullmatch(r'\[(\d{1,5}),(\d{1,5})\]\[(\d{1,5}),(\d{1,5})\]', element.get('bounds', ''))
            if not match or element.get('clickable') not in ('true', 'false'):
                raise ValueError('invalid bounds/clickability')
            l, t, r, b = map(int, match.groups())
            if not (0 <= l < r <= width and 0 <= t < b <= height):
                raise ValueError('out-of-frame node')
            nodes.append(Node(rid, text, element.get('clickable') == 'true', (l,t,r,b)))
        return tuple(nodes)
    except (ET.ParseError, ValueError) as error:
        raise RuntimeStop('malformed hierarchy') from error


@dataclass(frozen=True)
class Frame:
    binding: str
    sequence: int
    png: bytes
    xml: bytes
    width: int
    height: int
    nodes: tuple[Node, ...]

    @property
    def frame_sha256(self):
        return sha256(self.png).hexdigest()

    @property
    def evidence_sha256(self):
        return sha256(self.png + self.xml + self.binding.encode() + str(self.sequence).encode()).hexdigest()

    def resolve(self, resource_id: str, text: str, x=None, y=None):
        matches = [n for n in self.nodes if n.resource_id == resource_id and n.text == text and n.clickable]
        if len(matches) != 1:
            raise RuntimeStop('selector missing or ambiguous')
        l,t,r,b = matches[0].bounds
        if x is not None or y is not None:
            if type(x)is not int or type(y)is not int or not(l<=x<r and t<=y<b):
                raise RuntimeStop('native coordinates outside exact semantic target')
            return x,y
        return ((l+r)//2, (t+b)//2)

    def evidence(self):
        return dict(schema_version=1, binding=self.binding, sequence=self.sequence,
                    png_sha256=self.frame_sha256, xml_sha256=sha256(self.xml).hexdigest(),
                    evidence_sha256=self.evidence_sha256, width=self.width, height=self.height,
                    coherent=True, atomic=False)


class OwnedAdbTransport:
    """Runner must enforce timeout/output bounds DURING execution, never shell=True.

    owner marker is parent provisioned in disposable AVD /data/local/tmp.
    APK digest is read from installed base.apk, not inferred from an app label.
    """
    def __init__(self, target: OwnedTarget, runner: CmdRunner, clock, adb_path: str, adb_server_port: int = 5037):
        if not adb_path.startswith('/') or '\x00' in adb_path:
            raise ValueError('absolute adb executable required')
        if type(adb_server_port) is not int or not 1024 <= adb_server_port <= 65535:
            raise ValueError('invalid adb server port')
        self.adb_server_port = adb_server_port
        self.target, self.runner, self.clock, self.adb_path = target, runner, clock, adb_path
        self.sequence = 0

    def _cmd(self, args, deadline, maximum=1_048_576):
        remaining = deadline - self.clock.monotonic()
        if remaining <= 0:
            raise RuntimeStop('deadline')
        result = self.runner((self.adb_path, '-P', str(self.adb_server_port), '-s', self.target.serial, *args), min(5.0 if args == ('shell','uiautomator','dump','/data/local/tmp/reproloop-window.xml') else 2.0, remaining), maximum)
        if not isinstance(result, CommandResult) or len(result.stdout) + len(result.stderr) > maximum:
            raise RuntimeStop('runner output bound')
        if result.code != 0:
            raise RuntimeStop('command rejected/permission/safety')
        return result.stdout

    def discover(self, deadline):
        t = self.target
        checks = [ (('get-state',), 'device'),
                   (('emu', 'avd', 'name'), t.avd_name + '\nOK'),
                   (('shell', 'cat', '/proc/sys/kernel/random/boot_id'), t.boot_id),
                   (('shell', 'cat', '/data/local/tmp/reproloop-owner'), t.owner_id)]
        for args, expected in checks:
            if self._cmd(args, deadline).decode('utf-8').replace('\r\n','\n').strip() != expected:
                raise RuntimeStop('target identity mismatch')
        output = self._cmd(('shell','pm','path',PACKAGE), deadline).decode().strip()
        if not re.fullmatch(r'package:/data/app/[A-Za-z0-9_~+./=-]+/base\.apk', output) or '..' in output:
            raise RuntimeStop('unexpected APK path')
        apk = output.removeprefix('package:')
        actual = self._cmd(('shell','sha256sum',apk), deadline).decode().split()
        if actual != [t.apk_sha256, apk]:
            raise RuntimeStop('APK mismatch')

    def observe_capture_probe(self,png_before,xml,png_after,attempt,stable):
        """Read-only consistency record, never an atomic capture assertion."""
        record=dict(attempt=attempt,stable=stable,atomic=False,
                    png_before_sha256=sha256(png_before).hexdigest(),
                    png_after_sha256=sha256(png_after).hexdigest(),xml_sha256=sha256(xml).hexdigest())
        self.capture_probes.append(record)
        return record

    def capture(self, deadline):
        self.discover(deadline)
        self.capture_probes=[]
        # Screenshot -> hierarchy -> screenshot. Bound read-only resampling only;
        # no input, permission dismissal or stale-proposal replay occurs here.
        for attempt in (1,2):
            before=self._cmd(('exec-out','screencap','-p'),deadline,8_388_608)
            w,h=png_size(before)
            self._cmd(('shell','uiautomator','dump','/data/local/tmp/reproloop-window.xml'),deadline)
            xml=self._cmd(('exec-out','cat','/data/local/tmp/reproloop-window.xml'),deadline)
            nodes=parse_hierarchy(xml,w,h)  # foreign/malformed hierarchy stops immediately
            after=self._cmd(('exec-out','screencap','-p'),deadline,8_388_608)
            after_size=png_size(after)
            stable=(after_size==(w,h) and before==after)
            self.observe_capture_probe(before,xml,after,attempt,stable)
            self.discover(deadline)
            if stable:
                self.sequence+=1
                return Frame(self.target.binding,self.sequence,after,xml,w,h,nodes)
        raise RuntimeStop('unstable screenshot/hierarchy bracket; no input allowed')

    def tap(self, x, y, frame, deadline):
        if frame.binding != self.target.binding:
            raise RuntimeStop('stale frame binding')
        for v, extent in ((x,frame.width),(y,frame.height)):
            if type(v) is not int or not 0 <= v < extent:
                raise ValueError('integer bounded coordinates required')
        self.discover(deadline)  # every input, immediately before fixed argv
        self._cmd(('shell','input','tap',str(x),str(y)),deadline,4096)

    def read_app_state(self, deadline):
        self.discover(deadline)
        return self._cmd(('shell','run-as',PACKAGE,'cat','files/state.json'),deadline,1_000_000)

    def read_app_events(self, deadline):
        self.discover(deadline)
        return self._cmd(('shell','run-as',PACKAGE,'cat','files/events.jsonl'),deadline,2_000_000)
