"""Durable request admission. Integer nano-USD, no bytes-to-tokens estimate."""
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
import json
import re
import sqlite3

CONTEXT = 1_048_576

class MetaBlocked(RuntimeError):
    pass


def identity(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',value):
        raise ValueError('invalid request identity')
    return value


def integer(value,low,high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid bounded integer')
    return value


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int

    @classmethod
    def parse(cls, value, output_cap):
        if type(value) is not dict: raise ValueError('usage required')
        i=integer(value.get('input_tokens'),0,CONTEXT)
        o=integer(value.get('output_tokens'),0,output_cap)
        details=value.get('input_tokens_details',{})
        output_details=value.get('output_tokens_details',{})
        if type(details) is not dict or type(output_details) is not dict: raise ValueError('invalid usage details')
        c=integer(details.get('cached_tokens',0),0,i)
        r=integer(output_details.get('reasoning_tokens',0),0,o)
        if i+o > CONTEXT: raise ValueError('context usage exceeded')
        total=value.get('total_tokens',i+o)
        if type(total) is not int or total != i+o: raise ValueError('inconsistent total')
        return cls(i,o,c,r)

    @property
    def nano_usd(self):
        return (self.input_tokens-self.cached_tokens)*1250+self.cached_tokens*150+self.output_tokens*4250


class CostLedger:
    def __init__(self,path,budget_usd='20',max_calls=60):
        self.path=str(path)
        budget=Decimal(str(budget_usd))
        if not budget.is_finite() or not 0 < budget <= 20: raise ValueError('budget must be <=20 USD')
        self.budget=int(budget*1_000_000_000)
        self.max_calls=integer(max_calls,1,60)
        with self.tx() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1),budget INTEGER,max_calls INTEGER,halt TEXT);
            CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload_sha TEXT NOT NULL,state TEXT NOT NULL,reserved INTEGER NOT NULL,cost INTEGER,output_cap INTEGER,provider_id TEXT,usage TEXT,reason TEXT NOT NULL);''')
            old=db.execute('SELECT * FROM policy').fetchone()
            if old and (old['budget'],old['max_calls']) != (self.budget,self.max_calls):
                raise MetaBlocked('persisted budget policy mismatch')
            db.execute('INSERT OR IGNORE INTO policy VALUES(1,?,?,NULL)',(self.budget,self.max_calls))

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path,timeout=1,isolation_level=None); db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
            yield db
            if db.in_transaction: db.commit()
        finally: db.close()

    def get(self,request_id):
        with self.tx() as db:
            row=db.execute('SELECT * FROM attempts WHERE id=?',(request_id,)).fetchone()
            return dict(row) if row else None

    def reserve(self,request_id,payload_sha,kind,output_cap=0):
        identity(request_id)
        if not re.fullmatch('[0-9a-f]{64}',payload_sha): raise ValueError('invalid digest')
        if kind not in ('responses','upload'): raise ValueError('unsupported attempt kind')
        if kind=='responses': integer(output_cap,16,8192)
        reservation=CONTEXT*1250+output_cap*4250 if kind=='responses' else 0
        with self.tx() as db:
            row=db.execute('SELECT * FROM attempts WHERE id=?',(request_id,)).fetchone()
            if row:
                if (row['kind'],row['payload_sha'],row['output_cap']) != (kind,payload_sha,output_cap):
                    raise MetaBlocked('stable request identity conflict')
                return False
            if db.execute('SELECT halt FROM policy').fetchone()[0]: raise MetaBlocked('provider halted')
            if db.execute("SELECT 1 FROM attempts WHERE state IN ('PENDING','UNKNOWN')").fetchone(): raise MetaBlocked('unknown or pending outcome')
            n=db.execute("SELECT count(*) FROM attempts WHERE kind='responses'").fetchone()[0]
            if kind=='responses' and n>=self.max_calls: raise MetaBlocked('call cap')
            held=db.execute('SELECT coalesce(sum(CASE WHEN cost IS NOT NULL THEN cost ELSE reserved END),0) FROM attempts').fetchone()[0]
            if held+reservation>self.budget: raise MetaBlocked('budget exhausted')
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,NULL,NULL,?)',
                       (request_id,kind,payload_sha,'PENDING',reservation,None,output_cap,'intent committed'))
            return True

    def finish(self,request_id,state,reason,usage=None,provider_id=None,halt=False):
        if state not in ('COMPLETE','REJECTED','UNKNOWN','UPLOADED'): raise ValueError('invalid state')
        if provider_id is not None: identity(provider_id)
        with self.tx() as db:
            row=db.execute('SELECT * FROM attempts WHERE id=?',(request_id,)).fetchone()
            if not row or row['state'] not in ('PENDING','UNKNOWN'): raise MetaBlocked('terminal receipt cannot change')
            cost=usage.nano_usd if usage else (0 if state=='REJECTED' else None)
            if state=='COMPLETE' and (not isinstance(usage,Usage) or cost>row['reserved']): raise MetaBlocked('usage exceeds reservation')
            db.execute('UPDATE attempts SET state=?,reason=?,cost=?,provider_id=?,usage=? WHERE id=?',
                       (state,reason,cost,provider_id,json.dumps(usage.__dict__) if usage else None,request_id))
            if halt: db.execute('UPDATE policy SET halt=? WHERE id=1',(reason,))

    def status(self):
        with self.tx() as db:
            policy=db.execute('SELECT * FROM policy').fetchone()
            return dict(budget_nano_usd=self.budget,max_calls=self.max_calls,halt=policy['halt'],
                        attempts=[dict(row) for row in db.execute('SELECT id,kind,state,reserved,cost,reason FROM attempts ORDER BY rowid')])
