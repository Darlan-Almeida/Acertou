import asyncio
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as HttpResponse
from fastapi import Request
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.exc import IntegrityError
from .db import db_session, SessionLocal
from .models import Teacher, Quiz, Question, Alternative, Session, SessionQuestion, SessionAlternative, Participant, Response, now
from .schemas import Register, Login, QuizIn, SessionIn, JoinIn, AnswerIn
from .security import password_hash, teacher_token, current_teacher, new_participant_token, token_digest, participant_from_token, SECRET
from .services import hub, utc, iso, questions, alternatives, session_state, current_question, close_question, preview_question, activate_question, finish_session, report, export_csv

TERMINAL = ('FINISHED', 'CANCELLED')

async def tick():
    while True:
        await asyncio.sleep(0.3)
        with SessionLocal() as db:
            candidates = db.query(Session).filter(Session.status.in_(['WAITING','COUNTDOWN','QUESTION_PREVIEW','QUESTION_ACTIVE','SHOWING_RESULTS'])).all()
            for s in candidates:
                async with hub.locks[s.id]:
                    event = None
                    q = current_question(db, s)
                    if s.status == 'WAITING' and s.scheduled_start_at and utc(s.scheduled_start_at) <= now():
                        s.status='COUNTDOWN'; s.countdown_ends_at=now()+timedelta(seconds=3); s.started_at=now(); db.commit(); event='countdown_started'
                    elif s.status == 'COUNTDOWN' and utc(s.countdown_ends_at) <= now():
                        preview_question(db, s); event='question_preview_started'
                    elif s.status == 'QUESTION_PREVIEW' and q and utc(q.preview_ends_at) <= now():
                        activate_question(db, s); event='question_started'
                    elif s.status == 'QUESTION_ACTIVE' and q and utc(q.ends_at) <= now():
                        close_question(db, s, q); event='question_finished'
                    elif s.status == 'SHOWING_RESULTS' and s.auto_advance_seconds and q and utc(q.finished_at)+timedelta(seconds=s.auto_advance_seconds) <= now():
                        if s.current_position < len(questions(db,s.id)):
                            s.current_position+=1; preview_question(db,s); event='question_preview_started'
                        else:
                            finish_session(db,s); event='session_finished'
                    if event: await hub.publish(s.id,event,{'session_id':s.id})

@asynccontextmanager
async def lifespan(app):
    if SECRET == 'development-only-change-me' and os.getenv('DATABASE_URL','').startswith('postgresql'):
        raise RuntimeError('Configure SECRET_KEY para produção')
    task=asyncio.create_task(tick())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass

app=FastAPI(title='Acertou API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173').split(','), allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
_attempts=defaultdict(deque)

@app.middleware('http')
async def sensitive_rate_limit(request:Request, call_next):
    if request.url.path in ('/auth/login','/auth/register','/sessions/join') and request.method=='POST':
        key=(request.client.host if request.client else 'unknown',request.url.path)
        bucket=_attempts[key]; current=time.monotonic()
        while bucket and bucket[0] < current-60: bucket.popleft()
        limit=300 if request.url.path=='/sessions/join' else 30
        if len(bucket)>=limit: return HttpResponse('{"detail":"Muitas tentativas; aguarde um minuto"}',status_code=429,media_type='application/json')
        bucket.append(current)
    return await call_next(request)

def own_quiz(db, quiz_id, teacher):
    q=db.get(Quiz,quiz_id)
    if not q or q.teacher_id != teacher.id: raise HTTPException(404,'Quiz não encontrado')
    return q

def own_session(db, session_id, teacher):
    s=db.get(Session,session_id)
    if not s or s.teacher_id != teacher.id: raise HTTPException(404,'Sessão não encontrada')
    return s

def quiz_data(db,q):
    qs=db.query(Question).filter_by(quiz_id=q.id).order_by(Question.position).all()
    return {'id':q.id,'title':q.title,'description':q.description,'created_at':iso(q.created_at),'updated_at':iso(q.updated_at),
            'questions':[{'id':item.id,'text':item.text,'time_limit_seconds':item.time_limit_seconds,'points':item.points,
                          'alternatives':[{'text':a.text} for a in db.query(Alternative).filter_by(question_id=item.id).order_by(Alternative.position).all()],
                          'correct_index':next(i for i,a in enumerate(db.query(Alternative).filter_by(question_id=item.id).order_by(Alternative.position).all()) if a.is_correct)} for item in qs]}

def replace_questions(db,q,payload):
    for old in db.query(Question).filter_by(quiz_id=q.id).all():
        db.query(Alternative).filter_by(question_id=old.id).delete()
        db.delete(old)
    db.flush()
    for pos,item in enumerate(payload.questions,1):
        question=Question(quiz_id=q.id,text=item.text,time_limit_seconds=item.time_limit_seconds,points=item.points,position=pos)
        db.add(question); db.flush()
        for i,a in enumerate(item.alternatives): db.add(Alternative(question_id=question.id,text=a.text,position=i+1,is_correct=i==item.correct_index))
    db.commit()

@app.post('/auth/register')
async def register(payload:Register,db:DbSession=Depends(db_session)):
    email=payload.email.lower()
    if db.query(Teacher).filter_by(email=email).first(): raise HTTPException(409,'E-mail já cadastrado')
    user=Teacher(name=payload.name.strip(),email=email,password_hash=password_hash.hash(payload.password))
    db.add(user); db.commit(); db.refresh(user)
    return {'token':teacher_token(user.id),'teacher':{'id':user.id,'name':user.name,'email':user.email}}

@app.post('/auth/login')
async def login(payload:Login,db:DbSession=Depends(db_session)):
    user=db.query(Teacher).filter_by(email=payload.email.lower()).first()
    if not user or not password_hash.verify(payload.password,user.password_hash): raise HTTPException(401,'Credenciais inválidas')
    return {'token':teacher_token(user.id),'teacher':{'id':user.id,'name':user.name,'email':user.email}}

@app.get('/auth/me')
async def me(teacher:Teacher=Depends(current_teacher)): return {'id':teacher.id,'name':teacher.name,'email':teacher.email}

@app.get('/quizzes')
async def list_quizzes(db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    return [quiz_data(db,q) for q in db.query(Quiz).filter_by(teacher_id=teacher.id).order_by(Quiz.updated_at.desc()).all()]

@app.post('/quizzes')
async def create_quiz(payload:QuizIn,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    q=Quiz(teacher_id=teacher.id,title=payload.title,description=payload.description);db.add(q);db.flush();replace_questions(db,q,payload)
    return quiz_data(db,q)

@app.get('/quizzes/{quiz_id}')
async def get_quiz(quiz_id:int,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    return quiz_data(db,own_quiz(db,quiz_id,teacher))

@app.put('/quizzes/{quiz_id}')
async def update_quiz(quiz_id:int,payload:QuizIn,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    q=own_quiz(db,quiz_id,teacher);q.title=payload.title;q.description=payload.description;replace_questions(db,q,payload)
    return quiz_data(db,q)

@app.post('/quizzes/{quiz_id}/duplicate')
async def duplicate_quiz(quiz_id:int,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    source=quiz_data(db,own_quiz(db,quiz_id,teacher));source.pop('id');source.pop('created_at');source.pop('updated_at')
    for q in source['questions']: q.pop('id')
    source['title']+=' (cópia)'
    return await create_quiz(QuizIn.model_validate(source),db,teacher)

@app.delete('/quizzes/{quiz_id}')
async def delete_quiz(quiz_id:int,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    q=own_quiz(db,quiz_id,teacher)
    if db.query(Session).filter_by(quiz_id=q.id).first(): raise HTTPException(409,'Exclua as sessões deste quiz antes')
    for question in db.query(Question).filter_by(quiz_id=q.id).all(): db.query(Alternative).filter_by(question_id=question.id).delete();db.delete(question)
    db.delete(q);db.commit();return {'ok':True}

@app.get('/sessions')
async def list_sessions(db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    return [session_state(db,s,teacher=True) for s in db.query(Session).filter_by(teacher_id=teacher.id).order_by(Session.created_at.desc()).all()]

@app.post('/quizzes/{quiz_id}/sessions')
async def create_session(quiz_id:int,payload:SessionIn,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    q=own_quiz(db,quiz_id,teacher)
    if payload.scheduled_start_at and (not payload.scheduled_start_at.tzinfo or payload.scheduled_start_at <= now()): raise HTTPException(422,'Agendamento deve estar no futuro e incluir fuso horário')
    for _ in range(30):
        code=f'{secrets.randbelow(1000000):06d}'
        if not db.query(Session).filter_by(access_code=code).first(): break
    else: raise HTTPException(503,'Não foi possível gerar um código')
    s=Session(quiz_id=q.id,teacher_id=teacher.id,quiz_title=q.title,access_code=code,scheduled_start_at=payload.scheduled_start_at,
              auto_advance_seconds=payload.auto_advance_seconds,require_identifier=payload.require_identifier,show_ranking=payload.show_ranking)
    db.add(s);db.flush()
    for original in db.query(Question).filter_by(quiz_id=q.id).order_by(Question.position):
        snapshot=SessionQuestion(session_id=s.id,position=original.position,text=original.text,time_limit_seconds=original.time_limit_seconds,points=original.points)
        db.add(snapshot);db.flush()
        for a in db.query(Alternative).filter_by(question_id=original.id).order_by(Alternative.position): db.add(SessionAlternative(question_id=snapshot.id,text=a.text,is_correct=a.is_correct,position=a.position))
    db.commit();return session_state(db,s,teacher=True)

@app.get('/sessions/{session_id}')
async def get_session(session_id:int,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    return session_state(db,own_session(db,session_id,teacher),teacher=True)

@app.post('/sessions/join')
async def join(payload:JoinIn,db:DbSession=Depends(db_session)):
    if not payload.name.strip(): raise HTTPException(422,'Nome obrigatório')
    s=db.query(Session).filter(Session.access_code==payload.code,Session.status.notin_(TERMINAL)).first()
    if not s or s.status!='WAITING': raise HTTPException(404,'Sessão indisponível para entrada')
    if s.require_identifier and not (payload.identifier and payload.identifier.strip()): raise HTTPException(422,'Identificador obrigatório')
    async with hub.locks[s.id]:
        token=new_participant_token()
        p=Participant(session_id=s.id,name=payload.name.strip(),identifier=payload.identifier,reconnect_token_hash=token_digest(token))
        db.add(p);db.commit();db.refresh(p)
        await hub.publish(s.id,'participant_joined',{'participant_count':db.query(Participant).filter_by(session_id=s.id).count()})
    return {'token':token,'session_id':s.id,'participant_id':p.id,'state':session_state(db,s,p)}

@app.get('/sessions/{session_id}/participant')
async def participant_state(session_id:int,x_participant_token:str=Header(),db:DbSession=Depends(db_session)):
    s=db.get(Session,session_id)
    if not s: raise HTTPException(404,'Sessão não encontrada')
    return session_state(db,s,participant_from_token(x_participant_token,session_id,db))

@app.post('/sessions/{session_id}/answer')
async def answer(session_id:int,payload:AnswerIn,x_participant_token:str=Header(),db:DbSession=Depends(db_session)):
    async with hub.locks[session_id]:
        s=db.get(Session,session_id);p=participant_from_token(x_participant_token,session_id,db)
        q=current_question(db,s)
        if not q: raise HTTPException(409,'Nenhuma questão ativa')
        previous=db.query(Response).filter_by(participant_id=p.id,question_id=q.id).first()
        if previous:
            if previous.alternative_id==payload.alternative_id: return {'alternative_id':previous.alternative_id,'duplicate':True}
            raise HTTPException(409,'Resposta já registrada')
        if s.status!='QUESTION_ACTIVE' or q.status!='ACTIVE' or now() >= utc(q.ends_at): raise HTTPException(409,'Tempo da questão encerrado')
        a=db.query(SessionAlternative).filter_by(id=payload.alternative_id,question_id=q.id).first()
        if not a: raise HTTPException(422,'Alternativa inválida')
        elapsed=max(0,int((now()-utc(q.started_at)).total_seconds()*1000)-q.total_paused_ms)
        r=Response(session_id=s.id,participant_id=p.id,question_id=q.id,alternative_id=a.id,is_correct=a.is_correct,response_time_ms=elapsed,points_earned=q.points if a.is_correct else 0)
        db.add(r)
        try: db.commit()
        except IntegrityError: db.rollback();raise HTTPException(409,'Resposta já registrada')
        await hub.publish_to_teachers(s.id,'answer_submitted',{'question_id':q.id})
        return {'alternative_id':a.id,'duplicate':False}

@app.post('/sessions/{session_id}/{action}')
async def control(session_id:int,action:str,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    if action not in ('start','pause','resume','close','next','finish','cancel'): raise HTTPException(404,'Ação desconhecida')
    async with hub.locks[session_id]:
        s=own_session(db,session_id,teacher);q=current_question(db,s)
        if action=='start' and s.status=='WAITING':
            s.status='COUNTDOWN';s.started_at=now();s.countdown_ends_at=now()+timedelta(seconds=3);db.commit();event='countdown_started'
        elif action=='pause' and s.status=='QUESTION_ACTIVE' and q:
            q.paused_at=now();s.paused_remaining_ms=max(0,int((utc(q.ends_at)-utc(q.paused_at)).total_seconds()*1000));s.status='QUESTION_PAUSED';db.commit();event='question_paused'
        elif action=='resume' and s.status=='QUESTION_PAUSED' and q:
            instant=now();q.total_paused_ms+=int((instant-utc(q.paused_at)).total_seconds()*1000);q.paused_at=None
            q.ends_at=instant+timedelta(milliseconds=s.paused_remaining_ms or 0);s.paused_remaining_ms=None;s.status='QUESTION_ACTIVE';db.commit();event='question_resumed'
        elif action=='close' and s.status=='QUESTION_ACTIVE' and q:
            if now() < utc(q.ends_at):
                raise HTTPException(409,'O resultado só fica disponível ao terminar o tempo da questão')
            close_question(db,s,q)
            event='question_finished'
        elif action=='next' and s.status=='SHOWING_RESULTS':
            if s.current_position<len(questions(db,s.id)):
                s.current_position+=1;preview_question(db,s);event='question_preview_started'
            else: finish_session(db,s);event='session_finished'
        elif action=='finish' and s.status not in TERMINAL:
            finish_session(db,s);event='session_finished'
        elif action=='cancel' and s.status=='WAITING':
            finish_session(db,s,True);event='session_cancelled'
        else: raise HTTPException(409,'Ação inválida para o estado atual')
        await hub.publish(s.id,event,{'session_id':s.id})
        return session_state(db,s,teacher=True)

@app.get('/sessions/{session_id}/results')
async def results(session_id:int,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    return report(db,own_session(db,session_id,teacher))

@app.get('/sessions/{session_id}/ranking')
async def ranking(session_id:int,x_participant_token:str=Header(),db:DbSession=Depends(db_session)):
    s=db.get(Session,session_id);participant_from_token(x_participant_token,session_id,db)
    if s.status!='FINISHED' or not s.show_ranking: raise HTTPException(403,'Ranking indisponível')
    return [{'name':p['name'],'score':p['total_score'],'rank':p['rank']} for p in report(db,s)['students']]

@app.get('/sessions/{session_id}/export/{kind}')
async def export(session_id:int,kind:str,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    if kind not in ('summary','detailed','matrix'): raise HTTPException(404,'Formato desconhecido')
    s=own_session(db,session_id,teacher)
    return HttpResponse(export_csv(report(db,s),kind),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="acertou-{session_id}-{kind}.csv"'})

@app.delete('/sessions/{session_id}')
async def delete_session(session_id:int,db:DbSession=Depends(db_session),teacher:Teacher=Depends(current_teacher)):
    s=own_session(db,session_id,teacher)
    if s.status not in TERMINAL: raise HTTPException(409,'Encerre a sessão antes de excluir')
    for q in questions(db,s.id):
        db.query(Response).filter_by(question_id=q.id).delete()
        db.query(SessionAlternative).filter_by(question_id=q.id).delete()
        db.delete(q)
    db.query(Participant).filter_by(session_id=s.id).delete();db.delete(s);db.commit();return {'ok':True}

@app.websocket('/ws/sessions/{session_id}')
async def websocket(ws:WebSocket,session_id:int):
    protocols=[part.strip() for part in ws.headers.get('sec-websocket-protocol','').split(',')]
    token=protocols[1] if len(protocols)==2 and protocols[0]=='acertou' else ''
    role=ws.query_params.get('role','participant')
    participant_id=None
    with SessionLocal() as db:
        s=db.get(Session,session_id)
        if not s: await ws.close(code=4404);return
        try:
            if role=='teacher':
                from jwt import decode
                teacher_id=int(decode(token,SECRET,algorithms=['HS256'])['sub'])
                if s.teacher_id!=teacher_id: raise ValueError()
                state=session_state(db,s,teacher=True)
            else:
                participant=participant_from_token(token,session_id,db)
                participant_id=participant.id
                state=session_state(db,s,participant)
        except Exception: await ws.close(code=4401);return
    await ws.accept(subprotocol='acertou');hub.clients[session_id].add(ws)
    if role=='teacher': hub.teacher_clients[session_id].add(ws)
    if participant_id is not None:
        hub.participant_clients[session_id][participant_id].add(ws)
        state['connected_count']=hub.connected_count(session_id)
        await hub.publish(session_id,'participant_joined',{'connected_count':state['connected_count']})
    try:
        await ws.send_json({'event':'state','data':state})
        while True: await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError): pass
    finally:
        hub.clients[session_id].discard(ws)
        hub.teacher_clients[session_id].discard(ws)
        if participant_id is not None:
            hub.participant_clients[session_id][participant_id].discard(ws)
            if not hub.participant_clients[session_id][participant_id]:
                hub.participant_clients[session_id].pop(participant_id,None)
                await hub.publish(session_id,'participant_left',{'connected_count':hub.connected_count(session_id)})
