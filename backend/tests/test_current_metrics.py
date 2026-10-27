from datetime import datetime,timedelta,timezone
import pytest
from conftest import ingest_trusted_event
from test_trajectory import event_payload

BASE='/api/v1/student/courses/'
COURSE='machine-learning'

def overview(client,headers,course=COURSE):
    r=client.get(BASE+course+'/overview',headers=headers);assert r.status_code==200;return r.json()

def score(client,headers,key,outcome=1,correction=None,minutes=1):
    payload=event_payload(key,outcome=outcome,correction_of_event_id=correction,
                          occurred_at=datetime.now(timezone.utc)-timedelta(minutes=minutes))
    r=ingest_trusted_event(client,BASE+COURSE+'/events',headers=headers,json=payload)
    assert r.status_code==200,r.text
    return {**r.json(), '_payload':payload}

def test_no_effective_scores_has_no_fabricated_history(client,student_headers,teacher_headers):
    d=overview(client,student_headers)
    assert d['recent_accuracy']=={'value':None,'delta':'尚无有效评分','trend':[]}
    assert d['mastery']['trend']==[] and '无可比历史' in d['mastery']['delta']
    s=client.get('/api/v1/student/courses/summary',headers=student_headers).json()
    assert s['mastery_delta'] is None
    t=client.get('/api/v1/teacher/courses/'+COURSE+'/overview',headers=teacher_headers).json()
    assert t['average_accuracy'] is None

def test_new_score_duplicate_and_correction_share_one_current_metric(client,student_headers,teacher_headers):
    a=score(client,student_headers,'metric-first',1)
    d=overview(client,student_headers);assert d['recent_accuracy']['value']==100
    repeat=ingest_trusted_event(client,BASE+COURSE+'/events',headers=student_headers,json=a['_payload'])
    assert repeat.status_code==200 and repeat.json()['duplicate']
    assert '1次' in overview(client,student_headers)['recent_accuracy']['delta']
    score(client,student_headers,'metric-correction',0,correction=a['event_id'],minutes=0.5)
    d=overview(client,student_headers)
    assert d['recent_accuracy']['value']==0 and '1次' in d['recent_accuracy']['delta']
    assert d['mastery']['value']==d['course']['mastery'] and d['mastery']['trend']==[]
    t=client.get('/api/v1/teacher/courses/'+COURSE+'/overview',headers=teacher_headers).json()
    assert t['average_accuracy']==0
    snap=client.post('/api/v1/courses/'+COURSE+'/decision-snapshots:refresh',headers=teacher_headers,json={}).json()
    assert snap['aggregate']['average_accuracy']==0
    assert overview(client,student_headers,'ai-intro')['recent_accuracy']['value'] is None

def test_latest_thirty_scores_are_not_calendar_or_seed_points(client,student_headers):
    for i in range(31):score(client,student_headers,'window-'+str(i),0 if i==0 else 1,minutes=40-i)
    d=overview(client,student_headers)
    assert d['recent_accuracy']['value']==100
    assert d['recent_accuracy']['trend']==[] and '30次' in d['recent_accuracy']['delta']
    assert client.get('/api/v1/student/courses/summary',headers=student_headers).json()['mastery_delta'] is None
