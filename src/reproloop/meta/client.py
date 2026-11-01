"""Pinned standard-library HTTPS client; no network happens until explicit call."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import urllib.error
import urllib.request
from .ledger import CostLedger, MetaBlocked, Usage, identity, integer

BASE='https://api.meta.ai/v1'
MODEL='muse-spark-1.3'
MAX_BODY=24*1024*1024
MAX_RESPONSE=12*1024*1024


def strict_json(raw):
    if type(raw) is not bytes or len(raw)>MAX_BODY: raise ValueError('JSON byte bound')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def encode(value): return json.dumps(value,separators=(',',':'),allow_nan=False).encode()


def validate_payload(payload):
    if type(payload) is not dict: raise ValueError('request object required')
    allowed={'model','store','max_output_tokens','input','tools','text','instructions','include','reasoning','previous_response_id','parallel_tool_calls','meta_safety_replay_receipt'}
    if set(payload)-allowed or payload.get('model')!=MODEL or payload.get('store') is not False:
        raise ValueError('only pinned Spark Standard stateless Responses allowed')
    integer(payload.get('max_output_tokens'),16,8192)
    if type(payload.get('input')) not in (str,list) or not payload['input']: raise ValueError('input required')
    if 'tools' in payload and payload['tools'] not in ([],[{'type':'computer'}]): raise ValueError('only computer tool permitted')
    if 'parallel_tool_calls' in payload and payload['parallel_tool_calls'] is not False: raise ValueError('parallel calls not enabled')
    if 'include' in payload and payload['include'] != ['reasoning.encrypted_content']: raise ValueError('unsupported include')
    if 'reasoning' in payload and (type(payload['reasoning']) is not dict or set(payload['reasoning'])!={'effort'} or payload['reasoning']['effort'] not in ('minimal','low','medium','high','xhigh')): raise ValueError('unsupported reasoning')
    # Disallow remote URL references, function/search tools even in replayed items.
    def walk(value,depth=0):
        if depth>32: raise ValueError('request depth bound')
        if isinstance(value,dict):
            if value.get('type') in ('function_call','function_call_output','web_search','web_search_call','image_generation'): raise ValueError('unsupported tool')
            for key,item in value.items():
                if key in ('video_url','image_url','url') and isinstance(item,str) and not item.startswith('data:image/png;base64,'): raise ValueError('external URLs forbidden')
                walk(item,depth+1)
        elif isinstance(value,list):
            if len(value)>2048: raise ValueError('item count bound')
            for item in value: walk(item,depth+1)
        elif isinstance(value,float): raise ValueError('float fields not enabled')
    walk(payload)
    raw=encode(payload)
    if len(raw)>MAX_BODY: raise ValueError('request byte bound')
    return raw


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

class MetaTransport:
    def __init__(self,timeout=60):
        if type(timeout) not in (int,float) or not 0<timeout<=60: raise ValueError('timeout bound')
        self.timeout=timeout
        # Ignore ambient proxies; pinned HTTPS endpoint only. System CA validation remains enabled.
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def request(self,method,path,key,body=None,content_type='application/json'):
        if not ((method=='POST' and path in ('/responses','/files')) or (method=='GET' and re.fullmatch(r'/responses/resp_[A-Za-z0-9_-]{1,120}',path))): raise ValueError('endpoint not allowed')
        req=urllib.request.Request(BASE+path,data=body,method=method,headers={'Authorization':'Bearer '+key,'Content-Type':content_type,'Accept':'application/json'})
        try:
            with self.opener.open(req,timeout=self.timeout) as response:
                raw=response.read(MAX_RESPONSE+1)
                if len(raw)>MAX_RESPONSE: raise MetaBlocked('provider output bound; charge unknown')
                return HttpResult(response.status,raw)
        except urllib.error.HTTPError as error:
            # Never retain/echo provider error strings, headers or potentially echoed secrets.
            status=error.code
            error.close()
            return HttpResult(status,b'')


class MetaClient:
    def __init__(self,ledger:CostLedger,transport=None):
        self.ledger=ledger; self.transport=transport or MetaTransport()

    def _result(self,request_id,result,key,output_cap,upload_size=None):
        if result.status in (400,401,403,404,413,415,422,429):
            self.ledger.finish(request_id,'REJECTED','HTTP_'+str(result.status),halt=result.status in (401,403,429))
            return {'request_id':request_id,'state':'REJECTED','reason':'HTTP_'+str(result.status)}
        if not 200<=result.status<300:
            self.ledger.finish(request_id,'UNKNOWN','HTTP_UNCERTAIN',halt=True)
            return {'request_id':request_id,'state':'UNKNOWN','reason':'HTTP_UNCERTAIN'}
        provider_id=None
        try:
            # Scrub exact in-memory credential before JSON is exposed or persisted.
            if type(result.body) is not bytes or len(result.body)>MAX_RESPONSE: raise ValueError('response byte bound')
            raw=result.body.replace(key.encode(),b'[REDACTED]')
            value=strict_json(raw)
            if type(value) is not dict: raise ValueError('response object required')
            value=strict_json(encode(value).replace(key.encode(),b'[REDACTED]'))
            if upload_size is not None:
                file_id=value.get('id')
                if type(file_id) is not str or not re.fullmatch('file-[A-Za-z0-9_-]{1,120}',file_id) or type(value.get('bytes')) is not int or value['bytes']!=upload_size or value.get('purpose')!='user_data': raise ValueError('upload metadata mismatch')
                self.ledger.finish(request_id,'UPLOADED','FILE_METADATA_VERIFIED',provider_id=file_id)
            else:
                candidate=value.get('id')
                if type(candidate) is str and re.fullmatch('resp_[A-Za-z0-9_-]{1,120}',candidate): provider_id=candidate
                if value.get('model')!=MODEL or value.get('status') not in ('completed','incomplete','failed','cancelled') or type(value.get('id')) is not str or not re.fullmatch('resp_[A-Za-z0-9_-]{1,120}',value['id']): raise ValueError('response metadata mismatch')
                usage=Usage.parse(value.get('usage'),output_cap)
                self.ledger.finish(request_id,'COMPLETE','MEASURED_USAGE',usage,value['id'])
            return {'request_id':request_id,'state':'UPLOADED' if upload_size is not None else 'COMPLETE','response':value}
        except (ValueError,TypeError,RecursionError,MetaBlocked):
            self.ledger.finish(request_id,'UNKNOWN','MISSING_OR_INVALID_RECEIPT',provider_id=provider_id)
            return {'request_id':request_id,'state':'UNKNOWN','reason':'MISSING_OR_INVALID_RECEIPT'}

    def responses(self,request_id,payload,key):
        raw=validate_payload(payload); cap=payload['max_output_tokens']
        if not self.ledger.reserve(request_id,sha256(raw).hexdigest(),'responses',cap):
            return {'request_id':request_id,'duplicate':True,'state':self.ledger.get(request_id)['state']}
        try: result=self.transport.request('POST','/responses',key,raw)
        except Exception:
            self.ledger.finish(request_id,'UNKNOWN','TRANSPORT_UNKNOWN')
            return {'request_id':request_id,'state':'UNKNOWN','reason':'TRANSPORT_UNKNOWN'}
        return self._result(request_id,result,key,cap)

    def reconcile(self,request_id,key):
        """GET only a provider ID observed on the original response. No new POST."""
        row=self.ledger.get(request_id)
        if not row or row['kind']!='responses' or row['state'] not in ('PENDING','UNKNOWN') or not row['provider_id']:
            raise MetaBlocked('no original provider ID; manual provider evidence required')
        try: result=self.transport.request('GET','/responses/'+row['provider_id'],key)
        except Exception: return {'request_id':request_id,'state':'UNKNOWN','reason':'READBACK_UNAVAILABLE'}
        # GET failure does NOT establish original POST rejection or release cost.
        if result.status!=200: return {'request_id':request_id,'state':'UNKNOWN','reason':'READBACK_UNAVAILABLE'}
        try:
            value=strict_json(result.body)
            if value.get('id')!=row['provider_id']: raise ValueError('readback identity mismatch')
        except (ValueError,AttributeError): raise MetaBlocked('readback identity mismatch')
        return self._result(request_id,result,key,row['output_cap'])

    def upload(self,request_id,relative_path,media_root,key):
        if type(relative_path) is not str or not relative_path or Path(relative_path).is_absolute() or '..' in Path(relative_path).parts: raise ValueError('relative media path required')
        root=Path(media_root).resolve(strict=True); candidate=(root/relative_path)
        # Reject every symlink component; open O_NOFOLLOW and check fstat, not URL fetching.
        current=root
        for part in Path(relative_path).parts:
            current=current/part
            if current.is_symlink(): raise ValueError('media symlinks forbidden')
        resolved=candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved.suffix.lower()!='.mp4': raise ValueError('MP4 root allowlist')
        directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            parts=Path(relative_path).parts
            for part in parts[:-1]:
                next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                os.close(directory); directory=next_fd
            fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        finally: os.close(directory)
        try:
            import stat
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 12<=info.st_size<=16*1024*1024: raise ValueError('media size/type bound')
            with os.fdopen(fd,'rb',closefd=False) as file: media=file.read(16*1024*1024+1)
            if len(media)!=info.st_size or media[4:8]!=b'ftyp': raise ValueError('MP4 changed/invalid header')
        finally: os.close(fd)
        payload_sha=sha256(b'purpose=user_data;expires=86400;'+media).hexdigest()
        if not self.ledger.reserve(request_id,payload_sha,'upload'): return {'request_id':request_id,'duplicate':True,'state':self.ledger.get(request_id)['state']}
        boundary='ReproLoop'+secrets.token_hex(16)
        parts=[]
        for name,value in [('purpose','user_data'),('expires_after[anchor]','created_at'),('expires_after[seconds]','86400')]:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="capture.mp4"\r\nContent-Type: video/mp4\r\n\r\n'.encode()+media+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        try: result=self.transport.request('POST','/files',key,b''.join(parts),'multipart/form-data; boundary='+boundary)
        except Exception:
            self.ledger.finish(request_id,'UNKNOWN','UPLOAD_TRANSPORT_UNKNOWN')
            return {'request_id':request_id,'state':'UNKNOWN','reason':'UPLOAD_TRANSPORT_UNKNOWN'}
        return self._result(request_id,result,key,0,len(media))
