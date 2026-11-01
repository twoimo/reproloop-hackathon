import json
import pathlib
import re
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from reproloop.meta.ledger import CostLedger, Usage, MetaBlocked, CONTEXT
from reproloop.meta.client import MetaClient, MetaTransport, HttpResult, MODEL, encode, validate_payload, NoRedirect
from reproloop.meta.gateway import GatewayApp, make_handler

KEY='test-secret-never-persist-123456'
PAYLOAD={'model':MODEL,'store':False,'max_output_tokens':100,'input':'synthetic test'}

def response(usage=True):
    value={'id':'resp_test','model':MODEL,'status':'completed','output':[]}
    if usage:value['usage']={'input_tokens':1000,'output_tokens':100,'total_tokens':1100,'input_tokens_details':{'cached_tokens':200},'output_tokens_details':{'reasoning_tokens':50}}
    return value

class FakeTransport:
    def __init__(self):self.calls=[]; self.result=HttpResult(200,encode(response())); self.fail=False; self.before=None
    def request(self,*args):
        self.calls.append(args)
        if self.before:self.before()
        if self.fail:raise TimeoutError(KEY)
        return self.result

class MetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        self.ledger=CostLedger(self.root/'ledger.sqlite')
        self.transport=FakeTransport();self.client=MetaClient(self.ledger,self.transport)
    def test_pending_committed_before_http_and_cost_measured_once(self):
        self.transport.before=lambda:self.assertEqual(self.ledger.get('a')['state'],'PENDING')
        result=self.client.responses('a',PAYLOAD,KEY)
        self.assertEqual(result['state'],'COMPLETE')
        row=self.ledger.get('a');self.assertEqual(row['cost'],800*1250+200*150+100*4250)
        self.assertEqual(row['reserved'],CONTEXT*1250+100*4250)
        self.assertTrue(self.client.responses('a',PAYLOAD,KEY)['duplicate']);self.assertEqual(len(self.transport.calls),1)
    def test_unknown_timeout_and_missing_usage_block_new_id(self):
        for missing in (False,True):
            with self.subTest(missing=missing):
                ledger=CostLedger(self.root/('missing' if missing else 'timeout'))
                transport=FakeTransport();transport.fail=not missing;transport.result=HttpResult(200,encode(response(False)))
                client=MetaClient(ledger,transport)
                self.assertEqual(client.responses('a',PAYLOAD,KEY)['state'],'UNKNOWN')
                with self.assertRaises(MetaBlocked):client.responses('b',PAYLOAD,KEY)
                self.assertIsNone(ledger.get('a')['cost'])
    def test_restart_never_replays_pending_and_conflict_rejected(self):
        self.ledger.reserve('a','a'*64,'responses',100)
        restarted=CostLedger(self.ledger.path)
        with self.assertRaises(MetaBlocked): restarted.reserve('b','b'*64,'responses',100)
        self.assertFalse(restarted.reserve('a','a'*64,'responses',100))
        with self.assertRaises(MetaBlocked):restarted.reserve('a','b'*64,'responses',100)
    def test_http_reject_vs_server_unknown_and_warning_halt(self):
        self.transport.result=HttpResult(400,KEY.encode())
        self.assertEqual(self.client.responses('a',PAYLOAD,KEY)['state'],'REJECTED')
        self.assertEqual(self.ledger.get('a')['cost'],0)
        self.transport.result=HttpResult(429,b'')
        self.client.responses('b',PAYLOAD,KEY)
        with self.assertRaises(MetaBlocked):self.client.responses('c',PAYLOAD,KEY)
        self.assertEqual(self.ledger.status()['halt'],'HTTP_429')
    def test_budget_policy_and_call_caps_are_durable(self):
        ledger=CostLedger(self.root/'small','1')
        with self.assertRaises(MetaBlocked):MetaClient(ledger,self.transport).responses('a',PAYLOAD,KEY)
        cap=CostLedger(self.root/'cap',max_calls=1);client=MetaClient(cap,self.transport)
        client.responses('a',PAYLOAD,KEY)
        with self.assertRaises(MetaBlocked):client.responses('b',PAYLOAD,KEY)
        with self.assertRaises(MetaBlocked):CostLedger(cap.path,max_calls=2)
        with self.assertRaises(ValueError):CostLedger(self.root/'bad','21')
    def test_usage_negative_variants(self):
        for field,value in [('input_tokens',True),('output_tokens',101),('input_tokens',CONTEXT),('total_tokens',0),('input_tokens_details',[]),('output_tokens_details',{'reasoning_tokens':101}),('input_tokens_details',{'cached_tokens':1001})]:
            usage=response()['usage'];usage[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):Usage.parse(usage,100)
        usage=Usage.parse(response()['usage'],100)
        self.assertEqual(usage.nano_usd,1455000) # reasoning already within output100
    def test_unsafe_provider_and_tools_and_unknown_properties(self):
        for patch in ({'model':'other'},{'store':True},{'tools':[{'type':'web_search'}]},{'mode':'contributor'},{'stream':True},{'input':[{'type':'input_image','image_url':'https://evil/'}]},{'max_output_tokens':8193}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_payload(dict(PAYLOAD,**patch))
        self.assertEqual(len(self.transport.calls),0)
        with self.assertRaises(ValueError):MetaTransport().request('POST','https://evil',KEY)
        self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))
    def test_provider_readback_only_original_id(self):
        self.transport.result=HttpResult(200,encode(response(False)))
        self.client.responses('a',PAYLOAD,KEY)
        self.transport.result=HttpResult(200,encode(response()))
        self.assertEqual(self.client.reconcile('a',KEY)['state'],'COMPLETE')
        self.assertEqual(self.transport.calls[-1][:2],('GET','/responses/resp_test'))
        with self.assertRaises(MetaBlocked):self.client.reconcile('missing',KEY)
    def test_redaction_no_key_in_ledger_or_errors(self):
        value=response();value['output']=[{'text':KEY}]
        self.transport.result=HttpResult(200,encode(value))
        result=self.client.responses('a',PAYLOAD,KEY)
        self.assertNotIn(KEY,repr(result));self.assertNotIn(KEY,str(self.ledger.status()))
        self.assertNotIn(KEY.encode(),(self.root/'ledger.sqlite').read_bytes())
    def test_upload_fixed_metadata_root_size_and_unknown(self):
        media=b'\x00\x00\x00\x18ftypisom'+b'\x00'*12
        (self.root/'clip.mp4').write_bytes(media)
        self.transport.result=HttpResult(200,encode({'id':'file-test','bytes':len(media),'purpose':'user_data'}))
        result=self.client.upload('u','clip.mp4',self.root,KEY)
        self.assertEqual(result['state'],'UPLOADED');self.assertIsNone(self.ledger.get('u')['cost'])
        body=self.transport.calls[-1][3]
        for term in (b'user_data',b'expires_after[anchor]',b'created_at',b'expires_after[seconds]',b'86400',b'video/mp4'):self.assertIn(term,body)
        for path in ('../clip.mp4',str(self.root/'clip.mp4'),'missing.mp4'):
            with self.assertRaises((ValueError,FileNotFoundError)):self.client.upload('bad',path,self.root,KEY)
        (self.root/'link.mp4').symlink_to(self.root/'clip.mp4')
        with self.assertRaises(ValueError):self.client.upload('bad','link.mp4',self.root,KEY)
    def test_unknown_upload_blocks_inference_and_never_reuploads(self):
        (self.root/'clip.mp4').write_bytes(b'\x00\x00\x00\x18ftypisom'+b'\x00'*12)
        self.transport.fail=True
        self.assertEqual(self.client.upload('u','clip.mp4',self.root,KEY)['state'],'UNKNOWN')
        self.assertTrue(self.client.upload('u','clip.mp4',self.root,KEY)['duplicate'])
        with self.assertRaises(MetaBlocked):self.client.responses('a',PAYLOAD,KEY)
        self.assertEqual(len(self.transport.calls),1)
    def test_actual_urllib_request_construction_without_network(self):
        transport=MetaTransport()
        seen=[]
        class Body:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,maximum):return b'{}'
        class Opener:
            def open(self,request,timeout):
                seen.append((request,timeout));return Body()
        transport.opener=Opener()
        self.assertEqual(transport.request('POST','/responses',KEY,b'{}').status,200)
        request,timeout=seen[0]
        self.assertEqual(request.full_url,'https://api.meta.ai/v1/responses')
        self.assertEqual(request.get_header('Authorization'),'Bearer '+KEY)
        self.assertEqual(timeout,60);self.assertEqual(len(seen),1)
    def test_concurrent_admission_only_one_owner(self):
        results=[]
        def run(value):
            try:results.append(self.ledger.reserve(value,value*64,'responses',100))
            except MetaBlocked:results.append(False)
        threads=[threading.Thread(target=run,args=(value,)) for value in ('a','b')]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(results.count(True),1)

class GatewayTests(unittest.TestCase):
    def setUp(self):
        MetaTests.setUp(self);self.app=GatewayApp(self.client,self.root)
        reply=self.app.handle('GET','/configure',{'Host':'127.0.0.1:8769'})
        self.csrf=re.search(b'name="csrf" value="([^"]+)"',reply.body).group(1).decode()
        cookie=dict(reply.extra)['Set-Cookie'].split(';')[0]
        self.headers={'Host':'127.0.0.1:8769','Origin':'http://127.0.0.1:8769','Cookie':cookie,'X-ReproLoop-CSRF':self.csrf,'X-ReproLoop-Request-ID':'a','Content-Type':'application/json'}
    def configure(self):
        self.app.configure_from_trusted_ipc(KEY)
    def test_gateway_configure_secret_memory_only_and_status(self):
        self.configure()
        self.assertEqual(json.loads(self.app.handle('GET','/status',self.headers).body),{'configured':True})
        self.assertNotIn(KEY.encode(),(self.root/'ledger.sqlite').read_bytes())
        with self.assertRaises(ValueError):self.configure()
        headers=dict(self.headers,**{'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(self.app.handle('POST','/configure',headers,urlencode({'api_key':KEY,'csrf':self.csrf}).encode()).status,403)
        page=self.app.handle('GET','/configure',{'Host':'127.0.0.1:8769'})
        self.assertNotIn(b'type="password"',page.body)
    def test_gateway_host_origin_csrf_session_and_body(self):
        self.configure()
        variants=[dict(self.headers,Host='evil'),dict(self.headers,Origin='https://evil'),{k:v for k,v in self.headers.items() if k!='Cookie'},dict(self.headers,**{'X-ReproLoop-CSRF':'wrong'})]
        for headers in variants:self.assertEqual(self.app.handle('POST','/api/responses',headers,encode(PAYLOAD)).status,403)
        self.assertEqual(self.app.handle('POST','/api/responses',self.headers,b'x'*(24*1024*1024+1)).status,413)
        self.assertEqual(len(self.transport.calls),0)
    def test_gateway_parent_header_requires_session_and_csrf(self):
        self.configure();headers={k:v for k,v in self.headers.items() if k!='Origin'}
        self.assertEqual(self.app.handle('POST','/api/responses',headers,encode(PAYLOAD)).status,403)
        headers['X-ReproLoop-Client']='parent-local'
        self.assertEqual(self.app.handle('POST','/api/responses',headers,encode(PAYLOAD)).status,200)
    def test_gateway_provider_escaped_secret_redacted(self):
        self.configure();value=response();value['output']=[{'text':KEY}]
        raw=encode(value).replace(KEY.encode(),''.join('\\u%04x'%ord(c) for c in KEY).encode())
        self.transport.result=HttpResult(200,raw)
        reply=self.app.handle('POST','/api/responses',self.headers,encode(PAYLOAD))
        self.assertNotIn(KEY,reply.body.decode());self.assertEqual(reply.status,200)
    def test_http_handler_without_socket_enforces_security_headers(self):
        import io
        from email.message import Message
        handler_type=make_handler(self.app)
        handler=object.__new__(handler_type)
        handler.headers=Message();handler.headers['Host']='127.0.0.1:8769'
        handler.command='GET';handler.path='/configure';handler.rfile=io.BytesIO();handler.wfile=io.BytesIO()
        class Connection:
            def settimeout(self,value): pass
        handler.connection=Connection();headers=[];statuses=[]
        handler.send_response=statuses.append
        handler.send_header=lambda key,value:headers.append((key,value))
        handler.end_headers=lambda:None
        handler.do_GET()
        self.assertEqual(statuses,[200]);self.assertIn(('Cache-Control','no-store'),headers)
        self.assertIn(('X-Frame-Options','DENY'),headers)
        self.assertIn("frame-ancestors 'none'",dict(headers)['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin',dict(headers))
        self.assertIn('HttpOnly',dict(headers)['Set-Cookie']);self.assertIn('SameSite=Strict',dict(headers)['Set-Cookie'])
    def test_security_headers_and_no_logging_are_installed(self):
        handler=make_handler(self.app)
        self.assertIs(handler.do_GET,handler.do_POST)
        self.assertIsNone(handler.log_message(None,'secret'))

if __name__=='__main__':unittest.main()
