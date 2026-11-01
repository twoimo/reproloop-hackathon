"""Opt-in 127.0.0.1 gateway. Importing this module starts no server."""
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import argparse
import html
import json
from pathlib import Path
import re
import secrets
import os
import stat
import select
import threading
import time
from urllib.parse import parse_qs
from .client import MetaClient, strict_json, encode, MAX_BODY
from .ledger import CostLedger, MetaBlocked, identity


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    content_type: str = 'application/json'
    extra: tuple = ()


class GatewayApp:
    def __init__(self,client,media_root,port=8769):
        if type(port) is not int or not 1024<=port<=65535: raise ValueError('invalid port')
        self.client=client; self.media_root=Path(media_root).resolve(strict=True)
        if not self.media_root.is_dir(): raise ValueError('media root directory required')
        self.host=f'127.0.0.1:{port}'; self.origin='http://'+self.host
        self._key=None; self._sessions={}; self._lock=threading.RLock()

    @property
    def configured(self): return self._key is not None

    def configure_from_trusted_ipc(self,key):
        """Trusted local process entry only; never an HTTP action."""
        if type(key)is not str or not re.fullmatch(r'[A-Za-z0-9_.:/+=-]{16,512}',key):
            raise ValueError('invalid credential shape')
        with self._lock:
            if self.configured:raise ValueError('credential already configured')
            self._key=key

    def _session(self,headers):
        try:
            cookie=SimpleCookie(); cookie.load(headers.get('cookie',''))
            token=cookie['reproloop_session'].value
            csrf,created=self._sessions[token]
            if time.monotonic()-created>3600: return None
            return csrf
        except (KeyError,ValueError): return None

    def handle(self,method,path,headers,body=b''):
        # Testable HTTP boundary: callers need not start a local/network server.
        headers={str(k).lower():v for k,v in headers.items()}
        with self._lock:
            try: return self._handle(method,path,headers,body)
            except (ValueError,TypeError,KeyError,RecursionError): return Reply(400,b'{"error":"invalid bounded request"}')
            except MetaBlocked: return Reply(409,b'{"error":"budget or unknown-outcome gate"}')
            except Exception: return Reply(500,b'{"error":"operation unavailable"}')

    def _handle(self,method,path,headers,body):
        if headers.get('host')!=self.host: return Reply(403,b'{"error":"host denied"}')
        origin=headers.get('origin')
        if origin is not None and origin!=self.origin: return Reply(403,b'{"error":"origin denied"}')
        if method=='GET' and path=='/configure':
            self._sessions={k:v for k,v in self._sessions.items() if time.monotonic()-v[1]<3600}
            if len(self._sessions)>=32: return Reply(429,b'{"error":"session cap"}')
            session=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
            self._sessions[session]=(csrf,time.monotonic())
            page=f'''<!doctype html><html><head><title>ReproLoop local connection</title></head><body><h1>ReproLoop local connection</h1><p>HTTP credential entry is disabled. Keys enter through an owner-only memory pipe, never a web form or plaintext file.</p><input type="hidden" name="csrf" value="{html.escape(csrf)}"><a href="/status">Connection status</a></body></html>'''
            return Reply(200,page.encode(),'text/html; charset=utf-8',(('Set-Cookie','reproloop_session='+session+'; Path=/; HttpOnly; SameSite=Strict'),))
        csrf=self._session(headers)
        if not csrf: return Reply(403,b'{"error":"session required"}')
        if method=='GET' and path=='/status': return Reply(200,encode({'configured':self.configured}))
        if method!='POST': return Reply(404,b'{"error":"not found"}')
        if origin!=self.origin and headers.get('x-reproloop-client')!='parent-local': return Reply(403,b'{"error":"explicit local client required"}')
        if type(body) is not bytes or len(body)>MAX_BODY: return Reply(413,b'{"error":"body bound"}')
        content_type=headers.get('content-type','').split(';')[0]
        if path=='/configure':
            return Reply(403,b'{"error":"HTTP credential entry disabled; use owner-only IPC"}')
        if not secrets.compare_digest(headers.get('x-reproloop-csrf',''),csrf): return Reply(403,b'{"error":"csrf denied"}')
        if content_type!='application/json': return Reply(415,b'{"error":"JSON required"}')
        if not self.configured: return Reply(409,b'{"error":"key not configured"}')
        request_id=identity(headers.get('x-reproloop-request-id'))
        value=strict_json(body)
        if path=='/api/responses': result=self.client.responses(request_id,value,self._key)
        elif path=='/api/upload':
            if type(value) is not dict or set(value)!={'path'}: raise ValueError('upload path only')
            result=self.client.upload(request_id,value['path'],self.media_root,self._key)
        else: return Reply(404,b'{"error":"not found"}')
        # Defense in depth: scrub parsed JSON as well as provider raw body, including
        # escaped provider representations. Never return transport exception strings.
        raw=encode(result).replace(self._key.encode(),b'[REDACTED]')
        return Reply(200,raw)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version='ReproLoop'; sys_version=''
        def log_message(self,*args): pass
        def _dispatch(self):
            raw_lengths=self.headers.get_all('Content-Length',[])
            if self.headers.get('Transfer-Encoding') is not None or len(raw_lengths)>1 or len(self.headers.get_all('Host',[]))!=1:
                self.send_error(400); return
            try:
                length=int(raw_lengths[0]) if raw_lengths else 0
                if not 0<=length<=MAX_BODY: raise ValueError()
                self.connection.settimeout(5)
                body=self.rfile.read(length)
                if len(body)!=length: raise ValueError()
                reply=app.handle(self.command,self.path,dict(self.headers),body)
            except Exception: reply=Reply(400,b'{"error":"invalid request framing"}')
            self.send_response(reply.status)
            self.send_header('Content-Type',reply.content_type)
            self.send_header('Content-Length',str(len(reply.body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('X-Frame-Options','DENY'); self.send_header('X-Content-Type-Options','nosniff')
            for key,value in reply.extra: self.send_header(key,value)
            self.end_headers(); self.wfile.write(reply.body)
        do_GET=_dispatch; do_POST=_dispatch
    return Handler


def read_owner_fifo(path,timeout=30):
    """One-time POSIX0600 FIFO, no file data and no credential logging."""
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    info=os.fstat(fd)
    try:
        if not stat.S_ISFIFO(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
            raise ValueError('owner-only FIFO required')
        end=time.monotonic()+timeout;raw=bytearray()
        while time.monotonic()<end:
            ready,_,_=select.select([fd],[],[],min(.1,max(0,end-time.monotonic())))
            if not ready:continue
            chunk=os.read(fd,513)
            if chunk:
                raw.extend(chunk)
                if len(raw)>512:raise ValueError('credential bound')
            elif raw:
                value=raw.decode('ascii')
                if not re.fullmatch(r'[A-Za-z0-9_.:/+=-]{16,512}',value):raise ValueError('invalid credential shape')
                return value
            else:time.sleep(.02)
        raise TimeoutError('owner IPC timeout')
    finally:
        os.close(fd)
        try:
            current=path.lstat()
            if (current.st_dev,current.st_ino)==(info.st_dev,info.st_ino) and stat.S_ISFIFO(current.st_mode) and info.st_uid==os.getuid():path.unlink()
        except FileNotFoundError:pass


def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument('--state-dir',required=True); parser.add_argument('--media-root',required=True); parser.add_argument('--port',type=int,default=8769); parser.add_argument('--key-fifo')
    args=parser.parse_args(argv)
    state=Path(args.state_dir); state.mkdir(mode=0o700,parents=True,exist_ok=True)
    client=MetaClient(CostLedger(state/'meta-cost.sqlite'))
    app=GatewayApp(client,args.media_root,args.port)
    if args.key_fifo:app.configure_from_trusted_ipc(read_owner_fifo(args.key_fifo))
    # Exactly one loopback server; serial HTTP handling matches gateway memory lock.
    server=HTTPServer(('127.0.0.1',args.port),make_handler(app))
    try: server.serve_forever()
    finally: server.server_close(); app._key=None

if __name__=='__main__': main()
