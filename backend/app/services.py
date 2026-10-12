import asyncio
import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, WebSocket
from sqlalchemy.orm import Session as DbSession
from .models import Session, SessionQuestion, SessionAlternative, Participant, Response, now

def utc(value):
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def iso(value): return utc(value).isoformat() if value else None

def questions(db, session_id):
    return db.query(SessionQuestion).filter_by(session_id=session_id).order_by(SessionQuestion.position).all()

def alternatives(db, question_id):
    return db.query(SessionAlternative).filter_by(question_id=question_id).order_by(SessionAlternative.position).all()

def current_question(db, session):
    return db.query(SessionQuestion).filter_by(session_id=session.id, position=session.current_position).first()

PREVIEW_SECONDS = 5

def public_question(db, q, reveal=False):
    preview = q.status == 'PREVIEW'
    options = [] if preview else alternatives(db, q.id)
    data = {'id': q.id, 'number': q.position, 'text': q.text, 'time_limit_seconds': q.time_limit_seconds,
            'points': q.points, 'status': q.status, 'preview_ends_at': iso(q.preview_ends_at),
            'preview_seconds': PREVIEW_SECONDS, 'started_at': iso(q.started_at), 'ends_at': iso(q.ends_at),
            'paused_remaining_ms': q.time_limit_seconds * 1000 if q.status == 'PENDING' else None,
            'alternatives': [{'id': a.id, 'text': a.text, 'position': a.position} for a in options]}
    if reveal and not preview:
        data['correct_alternative_id'] = next(a.id for a in options if a.is_correct)
    return data

def session_state(db, session, participant=None, teacher=False):
    qs = questions(db, session.id)
    q = current_question(db, session)
    count = db.query(Participant).filter_by(session_id=session.id).count()
    reveal = teacher or (q and q.status == 'CLOSED')
    data = {'id': session.id, 'code': session.access_code, 'quiz_title': session.quiz_title, 'status': session.status,
            'current_position': session.current_position, 'total_questions': len(qs), 'participant_count': count,
            'connected_count': hub.connected_count(session.id),
            'server_time': iso(now()), 'countdown_ends_at': iso(session.countdown_ends_at),
            'paused_remaining_ms': session.paused_remaining_ms, 'scheduled_start_at': iso(session.scheduled_start_at),
            'show_ranking': session.show_ranking, 'question': public_question(db, q, reveal) if q else None}
    if participant:
        answered = db.query(Response).filter_by(participant_id=participant.id).all()
        own = next((r for r in answered if q and r.question_id == q.id), None)
        disclosed = [r for r in answered if not q or r.question_id != q.id or q.status == 'CLOSED']
        answer = {'alternative_id': own.alternative_id} if own else None
        if answer and q.status == 'CLOSED':
            answer.update({'is_correct': own.is_correct, 'points_earned': own.points_earned})
        data['participant'] = {'id': participant.id, 'name': participant.name, 'score': sum(r.points_earned for r in disclosed),
                               'correct': sum(r.is_correct for r in disclosed), 'answer': answer}
    if teacher:
        data['participants'] = [{'id': p.id, 'name': p.name, 'identifier': p.identifier,
                                 'connected': p.id in hub.participant_clients[session.id]} for p in db.query(Participant).filter_by(session_id=session.id).order_by(Participant.joined_at)]
    return data

class Hub:
    def __init__(self):
        self.clients = defaultdict(set)
        self.teacher_clients = defaultdict(set)
        self.participant_clients = defaultdict(lambda: defaultdict(set))
        self.locks = defaultdict(asyncio.Lock)

    def connected_count(self, session_id):
        return sum(bool(clients) for clients in self.participant_clients[session_id].values())

    async def publish(self, session_id, event, payload=None):
        message = {'event': event, 'data': payload or {}}
        for ws in list(self.clients[session_id]):
            try: await ws.send_json(message)
            except Exception: self.clients[session_id].discard(ws)

    async def publish_to_teachers(self, session_id, event, payload=None):
        message = {'event': event, 'data': payload or {}}
        for ws in list(self.teacher_clients[session_id]):
            try: await ws.send_json(message)
            except Exception: self.teacher_clients[session_id].discard(ws)

hub = Hub()

def close_question(db, session, q):
    if q and q.status == 'ACTIVE':
        q.status = 'CLOSED'
        q.finished_at = now()
        session.status = 'SHOWING_RESULTS'
        session.paused_remaining_ms = None
        db.commit()
        return True
    return False

def preview_question(db, session):
    if session.current_position == 0:
        session.current_position = 1
    q = current_question(db, session)
    if not q: raise HTTPException(409, 'Não há próxima questão')
    if q.status != 'PENDING': raise HTTPException(409, 'Questão já iniciada')
    q.status = 'PREVIEW'
    q.preview_ends_at = now() + timedelta(seconds=PREVIEW_SECONDS)
    session.status = 'QUESTION_PREVIEW'
    session.paused_remaining_ms = None
    db.commit()
    return q

def activate_question(db, session):
    q = current_question(db, session)
    if not q or q.status != 'PREVIEW': raise HTTPException(409, 'Prévia indisponível')
    q.status = 'ACTIVE'
    q.started_at = now()
    q.ends_at = q.started_at + timedelta(seconds=q.time_limit_seconds)
    session.status = 'QUESTION_ACTIVE'
    session.paused_remaining_ms = None
    db.commit()
    return q

def finish_session(db, session, cancelled=False):
    session.status = 'CANCELLED' if cancelled else 'FINISHED'
    session.finished_at = now()
    q = current_question(db, session)
    if q and q.status in ('ACTIVE', 'PREVIEW'):
        q.status = 'CLOSED'; q.finished_at = now()
    db.commit()

def report(db, session):
    qs = questions(db, session.id)
    people = db.query(Participant).filter_by(session_id=session.id).order_by(Participant.joined_at).all()
    rows = db.query(Response).filter_by(session_id=session.id).all()
    by_pair = {(r.participant_id, r.question_id): r for r in rows}
    options = {q.id: alternatives(db, q.id) for q in qs}
    students = []
    for p in people:
        details = []
        for q in qs:
            r = by_pair.get((p.id, q.id))
            selected = next((a for a in options[q.id] if r and a.id == r.alternative_id), None)
            correct = next(a for a in options[q.id] if a.is_correct)
            details.append({'question_number': q.position, 'question_id': q.id, 'question_text': q.text,
                            'selected_option': selected.position if selected else None, 'selected_option_text': selected.text if selected else None,
                            'correct_option': correct.position, 'correct_option_text': correct.text,
                            'result': 'UNANSWERED' if not r else 'CORRECT' if r.is_correct else 'INCORRECT',
                            'response_time_seconds': round(r.response_time_ms / 1000, 3) if r else None,
                            'points_earned': r.points_earned if r else 0})
        correct_count = sum(d['result'] == 'CORRECT' for d in details)
        wrong_count = sum(d['result'] == 'INCORRECT' for d in details)
        correct_time = sum((by_pair[(p.id, q.id)].response_time_ms for q in qs if (p.id, q.id) in by_pair and by_pair[(p.id, q.id)].is_correct), 0)
        students.append({'id': p.id, 'name': p.name, 'identifier': p.identifier, 'total_questions': len(qs),
                         'correct_answers': correct_count, 'wrong_answers': wrong_count, 'unanswered_questions': len(qs)-correct_count-wrong_count,
                         'total_score': sum(d['points_earned'] for d in details), 'accuracy_percentage': round(correct_count / len(qs)*100, 2) if qs else 0,
                         'correct_time_ms': correct_time, 'details': details})
    students.sort(key=lambda p: (-p['total_score'], -p['correct_answers'], p['correct_time_ms'], p['id']))
    for i, p in enumerate(students): p['rank'] = i+1
    analysis = []
    for q in qs:
        distribution = [{'position': a.position, 'text': a.text, 'count': sum(r.alternative_id == a.id for r in rows), 'is_correct': a.is_correct} for a in options[q.id]]
        correct_names = [p['name'] for p in students if p['details'][q.position-1]['result'] == 'CORRECT']
        wrong_names = [p['name'] for p in students if p['details'][q.position-1]['result'] == 'INCORRECT']
        missing_names = [p['name'] for p in students if p['details'][q.position-1]['result'] == 'UNANSWERED']
        analysis.append({'number': q.position, 'text': q.text, 'distribution': distribution,
                         'correct': correct_names, 'incorrect': wrong_names, 'unanswered': missing_names,
                         'accuracy_percentage': round(len(correct_names)/len(people)*100, 2) if people else 0})
    total = len(people)*len(qs)
    return {'session_id': session.id, 'session_date': iso(session.started_at or session.created_at), 'quiz_title': session.quiz_title,
            'summary': {'participants': len(people), 'questions': len(qs), 'correct': sum(r.is_correct for r in rows),
                        'incorrect': sum(not r.is_correct for r in rows), 'unanswered': total-len(rows),
                        'average_accuracy_percentage': round(sum(p['accuracy_percentage'] for p in students)/len(students), 2) if students else 0,
                        'average_response_time_seconds': round(sum(r.response_time_ms for r in rows)/len(rows)/1000, 3) if rows else None},
            'students': students, 'questions': analysis}

def safe_csv(value):
    value = '' if value is None else str(value)
    return "'" + value if value.startswith(('\t', '\r')) or value.lstrip(' ').startswith(('=', '+', '-', '@')) else value

def export_csv(data, kind):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';', lineterminator='\r\n')
    if kind == 'summary':
        fields = ['session_id','quiz_title','student_id','student_name','student_identifier','total_questions','correct_answers','wrong_answers','unanswered_questions','total_score','accuracy_percentage']
        writer.writerow(fields)
        for p in data['students']:
            row = [data['session_id'], data['quiz_title'], p['id'], p['name'], p['identifier']] + [p[k] for k in fields[5:]]
            writer.writerow([safe_csv(x) for x in row])
    elif kind == 'detailed':
        fields = ['session_id','session_date','quiz_title','student_id','student_name','student_identifier','question_number','question_text','selected_option','selected_option_text','correct_option','correct_option_text','result','response_time_seconds','points_earned']
        writer.writerow(fields)
        for p in data['students']:
            for d in p['details']:
                row = [data['session_id'],data['session_date'],data['quiz_title'],p['id'],p['name'],p['identifier']] + [d[k] for k in fields[6:]]
                writer.writerow([safe_csv(x) for x in row])
    else:
        fields = ['Aluno'] + [f'Q{i+1}' for i in range(data['summary']['questions'])] + ['Acertos','Erros','Não respondidas','Pontuação']
        writer.writerow(fields)
        for p in data['students']:
            row = [p['name']] + [1 if d['result']=='CORRECT' else 0 if d['result']=='INCORRECT' else '' for d in p['details']] + [p['correct_answers'],p['wrong_answers'],p['unanswered_questions'],p['total_score']]
            writer.writerow([safe_csv(x) for x in row])
    return '\ufeff' + out.getvalue()
