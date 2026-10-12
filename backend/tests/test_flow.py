import csv
import io
import os
from datetime import timedelta
import asyncio

os.environ['DATABASE_URL']='sqlite:///./test_acertou.db'
os.environ['SECRET_KEY']='test-secret-for-integration-tests'

import pytest
from httpx import AsyncClient, ASGITransport
from app.db import Base, engine, SessionLocal
from app.main import app
from app.models import SessionQuestion, now
from app.services import preview_question, activate_question, utc

@pytest.mark.anyio
async def test_complete_session_and_history():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    teacher=(await client.post('/auth/register',json={'name':'Prof Ana','email':'ana@example.com','password':'password123'})).json()
    headers={'Authorization':f"Bearer {teacher['token']}"}
    questions=[{'text':f'Pergunta {i}', 'time_limit_seconds':30 if i%2 else 20,'points':100,
                'alternatives':[{'text':'Certa'},{'text':'Errada'}],'correct_index':0} for i in range(1,6)]
    quiz=await client.post('/quizzes',json={'title':'Revisão','description':'Teste','questions':questions},headers=headers)
    assert quiz.status_code==200
    quiz_id=quiz.json()['id']
    session=(await client.post(f'/quizzes/{quiz_id}/sessions',json={},headers=headers)).json()
    sid=session['id']; code=session['code']
    assert len(code)==6
    joins=[(await client.post('/sessions/join',json={'code':code,'name':name})).json() for name in ['João','Maria','João']]
    assert len({j['participant_id'] for j in joins})==3
    assert (await client.post(f'/sessions/{sid}/start',headers=headers)).status_code==200
    # The scheduler uses these same persisted transitions.
    with SessionLocal() as db:
        from app.models import Session
        s=db.get(Session, sid)
        q=preview_question(db, s)
        assert 4 <= (utc(q.preview_ends_at)-now()).total_seconds() <= 5
    preview=(await client.get(f'/sessions/{sid}/participant',headers={'X-Participant-Token':joins[0]['token']})).json()
    assert preview['status']=='QUESTION_PREVIEW'
    assert preview['question']['text']=='Pergunta 1'
    assert preview['question']['alternatives']==[]
    assert 'correct_alternative_id' not in preview['question']
    assert (await client.post(f'/sessions/{sid}/answer',json={'alternative_id':1},headers={'X-Participant-Token':joins[0]['token']})).status_code==409
    with SessionLocal() as db: activate_question(db,db.get(Session,sid))
    states=[(await client.get(f'/sessions/{sid}/participant',headers={'X-Participant-Token':j['token']})).json() for j in joins]
    assert len({s['question']['id'] for s in states})==1
    assert len({s['question']['ends_at'] for s in states})==1
    assert all('correct_alternative_id' not in s['question'] for s in states)
    first=states[0]['question']; correct=first['alternatives'][0]['id']; wrong=first['alternatives'][1]['id']
    reply=await client.post(f'/sessions/{sid}/answer',json={'alternative_id':correct},headers={'X-Participant-Token':joins[0]['token']})
    assert reply.json()=={'alternative_id':correct,'duplicate':False}
    assert (await client.post(f'/sessions/{sid}/answer',json={'alternative_id':correct},headers={'X-Participant-Token':joins[0]['token']})).json()['duplicate'] is True
    hidden=(await client.get(f'/sessions/{sid}/participant',headers={'X-Participant-Token':joins[0]['token']})).json()
    assert hidden['participant']['answer']=={'alternative_id':correct}
    assert hidden['participant']['score']==0
    assert hidden['participant']['correct']==0
    assert (await client.post(f'/sessions/{sid}/close',headers=headers)).status_code==409
    assert (await client.post(f'/sessions/{sid}/answer',json={'alternative_id':wrong},headers={'X-Participant-Token':joins[0]['token']})).status_code==409
    assert (await client.post(f'/sessions/{sid}/answer',json={'alternative_id':wrong},headers={'X-Participant-Token':joins[1]['token']})).json()=={'alternative_id':wrong,'duplicate':False}
    assert (await client.post(f'/sessions/{sid}/pause',headers=headers)).status_code==200
    assert (await client.post(f'/sessions/{sid}/answer',json={'alternative_id':correct},headers={'X-Participant-Token':joins[2]['token']})).status_code==409
    assert (await client.post(f'/sessions/{sid}/resume',headers=headers)).status_code==200
    with SessionLocal() as db:
        q=db.get(SessionQuestion,first['id']);q.ends_at=now()-timedelta(seconds=1);db.commit()
    assert (await client.post(f'/sessions/{sid}/answer',json={'alternative_id':correct},headers={'X-Participant-Token':joins[2]['token']})).status_code==409
    assert (await client.post(f'/sessions/{sid}/close',headers=headers)).status_code==200
    revealed=(await client.get(f'/sessions/{sid}/participant',headers={'X-Participant-Token':joins[0]['token']})).json()
    assert revealed['participant']['answer']=={'alternative_id':correct,'is_correct':True,'points_earned':100}
    assert revealed['participant']['score']==100
    assert revealed['question']['correct_alternative_id']==correct
    for _ in range(4):
        state=(await client.post(f'/sessions/{sid}/next',headers=headers)).json()
        assert state['question']['status']=='PREVIEW'
        assert state['question']['alternatives']==[]
        with SessionLocal() as db:
            session=db.get(Session,sid)
            q=activate_question(db,session)
            q.ends_at=now()-timedelta(seconds=1)
            db.commit()
        await client.post(f'/sessions/{sid}/close',headers=headers)
    assert (await client.post(f'/sessions/{sid}/next',headers=headers)).json()['status']=='FINISHED'
    report=(await client.get(f'/sessions/{sid}/results',headers=headers)).json()
    assert report['summary']['correct']==1
    assert report['summary']['incorrect']==1
    assert report['summary']['unanswered']==13
    assert len(report['students'])==3
    assert all(len(p['details'])==5 for p in report['students'])
    assert (await client.get(f'/sessions/{sid}/results')).status_code==403
    detailed=await client.get(f'/sessions/{sid}/export/detailed',headers=headers)
    assert detailed.content.startswith(b'\xef\xbb\xbf')
    rows=list(csv.DictReader(io.StringIO(detailed.content.decode('utf-8-sig')),delimiter=';'))
    assert len(rows)==15
    assert sum(row['result']=='UNANSWERED' for row in rows)==13
    edited=[{**q,'text':f'Nova pergunta {i}'} for i,q in enumerate(questions,1)]
    assert (await client.put(f'/quizzes/{quiz_id}',json={'title':'Revisão atualizada','questions':edited},headers=headers)).status_code==200
    historical=(await client.get(f'/sessions/{sid}/results',headers=headers)).json()
    assert historical['quiz_title']=='Revisão'
    assert historical['students'][0]['details'][0]['question_text']=='Pergunta 1'
    other=(await client.post('/auth/register',json={'name':'Other','email':'other@example.com','password':'password123'})).json()
    assert ((await client.get(f'/sessions/{sid}/results',headers={'Authorization':f"Bearer {other['token']}"}))).status_code==404
    await client.aclose()

@pytest.mark.anyio
async def test_scheduled_start_and_server_timer():
    from app.models import Teacher, Quiz, Session, SessionQuestion, SessionAlternative
    from app.main import tick
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        teacher=Teacher(name='Test',email='timer@example.com',password_hash='unused');db.add(teacher);db.flush()
        quiz=Quiz(teacher_id=teacher.id,title='Timer',description='');db.add(quiz);db.flush()
        session=Session(quiz_id=quiz.id,teacher_id=teacher.id,quiz_title='Timer',access_code='654321',
                        scheduled_start_at=now()+timedelta(milliseconds=200),auto_advance_seconds=2)
        db.add(session);db.flush();sid=session.id
        q=SessionQuestion(session_id=sid,position=1,text='Pergunta',time_limit_seconds=1,points=10)
        db.add(q);db.flush();db.add(SessionAlternative(question_id=q.id,text='Sim',is_correct=True,position=1))
        db.add(SessionAlternative(question_id=q.id,text='Não',is_correct=False,position=2));db.commit()
    task=asyncio.create_task(tick())
    try:
        await asyncio.sleep(0.7)
        with SessionLocal() as db: assert db.get(Session,sid).status=='COUNTDOWN'
        await asyncio.sleep(3.3)
        with SessionLocal() as db:
            session=db.get(Session,sid)
            assert session.status=='QUESTION_PREVIEW'
            q=db.query(SessionQuestion).filter_by(session_id=sid).one()
            assert 4 <= (utc(q.preview_ends_at)-now()).total_seconds() <= 5
            q.preview_ends_at=now()-timedelta(seconds=1)
            db.commit()
        await asyncio.sleep(0.5)
        with SessionLocal() as db: assert db.get(Session,sid).status=='QUESTION_ACTIVE'
        await asyncio.sleep(3.5)
        with SessionLocal() as db: assert db.get(Session,sid).status=='FINISHED'
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task

def test_csv_formula_escape():
    from app.services import safe_csv
    for value in ['=SUM(1)', '+cmd', '-5', '@test', '\tformula']:
        assert safe_csv(value).startswith("'")

@pytest.fixture
def anyio_backend():
    return "asyncio"
