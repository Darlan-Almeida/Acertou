import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .db import db_session
from .models import Teacher, Participant

SECRET = os.getenv('SECRET_KEY', 'development-only-change-me')
ALGORITHM = 'HS256'
password_hash = PasswordHash.recommended()
bearer = HTTPBearer()

def teacher_token(teacher_id):
    return jwt.encode({'sub': str(teacher_id), 'exp': datetime.now(timezone.utc) + timedelta(days=7)}, SECRET, algorithm=ALGORITHM)

async def current_teacher(credentials: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(db_session)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=[ALGORITHM])
        teacher = db.get(Teacher, int(payload['sub']))
    except (jwt.PyJWTError, ValueError, KeyError):
        teacher = None
    if not teacher:
        raise HTTPException(401, 'Autenticação inválida')
    return teacher

def new_participant_token(): return secrets.token_urlsafe(32)
def token_digest(token): return hashlib.sha256(token.encode()).hexdigest()

def participant_from_token(token: str, session_id: int, db: Session):
    participant = db.query(Participant).filter_by(session_id=session_id, reconnect_token_hash=token_digest(token)).first()
    if not participant:
        raise HTTPException(401, 'Credencial de participante inválida')
    return participant
