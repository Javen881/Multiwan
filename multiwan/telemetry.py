"""Append-only, evidence-oriented telemetry. Never changes routes or NAT.

Only measured observations may be used as operational evidence. Dry-run rows are
labelled 'simulated' and omitted from production failure statistics.
"""
import datetime as dt
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 at INTEGER NOT NULL, wan TEXT NOT NULL, source_ip TEXT,
 target TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('gateway','internet','ip','application')),
 outcome TEXT NOT NULL CHECK(outcome IN ('success','timeout','network_error','refused','unknown')),
 latency_ms REAL, origin TEXT NOT NULL CHECK(origin IN ('measured','simulated')),
 detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS samples_lookup ON samples(wan,at);
CREATE INDEX IF NOT EXISTS samples_ip_lookup ON samples(source_ip,at);
CREATE TABLE IF NOT EXISTS decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
 scope TEXT NOT NULL, subject TEXT NOT NULL, action TEXT NOT NULL,
 reason TEXT NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decision_recent ON decisions(at);
"""

def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=5)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript(SCHEMA)
    return db

def log_sample(db, *, wan, target, outcome, kind='internet', source_ip=None, latency_ms=None,
               origin='measured', detail='', at=None):
    if kind not in ('gateway','internet','ip','application') or outcome not in ('success','timeout','network_error','refused','unknown') or origin not in ('measured','simulated'):
        raise ValueError('invalid probe classification')
    if latency_ms is not None and not 0 <= latency_ms <= 600000:
        raise ValueError('invalid probe latency')
    with db:
        db.execute('INSERT INTO samples(at,wan,source_ip,target,kind,outcome,latency_ms,origin,detail) VALUES(?,?,?,?,?,?,?,?,?)',
                   (int(time.time() if at is None else at),wan,source_ip,target,kind,outcome,latency_ms,origin,str(detail)[:500]))

def log_decision(db, *, scope, subject, action, reason, evidence, status='proposed', at=None):
    if status not in ('proposed','applied','rejected','recovered','failed'):
        raise ValueError('invalid decision status')
    with db:
        db.execute('INSERT INTO decisions(at,scope,subject,action,reason,evidence,status) VALUES(?,?,?,?,?,?,?)',
                   (int(time.time() if at is None else at), scope, subject, action, reason, json.dumps(evidence,ensure_ascii=False,sort_keys=True),status))

def get_dashboard(db, *, window=900, now=None, limit=100):
    now=int(time.time() if now is None else now)
    # Only real network failures; a target denial or RST is not a WAN outage.
    records=db.execute('''SELECT wan,source_ip,COUNT(*) n,
        SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) ok,
        SUM(CASE WHEN outcome IN ('timeout','network_error') THEN 1 ELSE 0 END) failed,
        COUNT(DISTINCT target) targets,
        AVG(CASE WHEN outcome='success' THEN latency_ms END) avg_latency
        FROM samples WHERE at >= ? AND at <= ? AND origin='measured'
        AND kind IN ('internet','ip','gateway') AND outcome != 'unknown'
        GROUP BY wan,source_ip ORDER BY wan,source_ip''',(now-window,now)).fetchall()
    metrics=[]
    for wan,source_ip,n,ok,failed,targets,latency in records:
        metrics.append({'wan':wan,'source_ip':source_ip,'samples':n,'successes':ok or 0,
                        'failures':failed or 0,'failure_rate':round((failed or 0)/n,4) if n else None,
                        'targets':targets,'avg_latency_ms':round(latency,1) if latency is not None else None})
    recent=db.execute('''SELECT at,wan,source_ip,target,kind,outcome,latency_ms,origin,detail
        FROM samples ORDER BY id DESC LIMIT ?''',(min(max(int(limit),1),500),)).fetchall()
    decisions=db.execute('''SELECT at,scope,subject,action,reason,evidence,status
        FROM decisions ORDER BY id DESC LIMIT ?''',(min(max(int(limit),1),500),)).fetchall()
    return {'window_seconds':window,'metrics':metrics,
            'samples':[dict(zip(('at','wan','source_ip','target','kind','outcome','latency_ms','origin','detail'),r)) for r in recent],
            'decisions':[dict(zip(('at','scope','subject','action','reason','evidence','status'),r)) for r in decisions]}

def evaluate_wan(db, wan, *, min_samples=12,min_targets=2,threshold=.6,at=None,window=60):
    """Explainable ADVISORY only; not permitted to disable interfaces automatically."""
    now=int(time.time() if at is None else at)
    row=db.execute('''SELECT COUNT(*), COUNT(DISTINCT target),
        SUM(CASE WHEN outcome IN ('timeout','network_error') THEN 1 ELSE 0 END)
        FROM samples WHERE wan=? AND at BETWEEN ? AND ? AND origin='measured'
        AND kind='internet' AND outcome IN ('success','timeout','network_error')''',
        (wan,now-window,now)).fetchone()
    samples,targets,failed=row
    rate=(failed or 0)/samples if samples else None
    sufficient=samples>=min_samples and targets>=min_targets
    return {'wan':wan,'samples':samples,'targets':targets,'failures':failed or 0,
            'failure_rate':rate,'sufficient':sufficient,
            'recommendation':'investigate' if sufficient and rate>=threshold else 'observe',
            'reason':'Multi-target measured failure rate; additional independent windows and per-IP evidence required before disabling WAN' if sufficient and rate>=threshold else 'Insufficient evidence or healthy'}
