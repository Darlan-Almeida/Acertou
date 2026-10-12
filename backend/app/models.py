from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now(): return datetime.now(timezone.utc)

class Teacher(Base):
    __tablename__ = 'teachers'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Quiz(Base):
    __tablename__ = 'quizzes'
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey('teachers.id', ondelete='CASCADE'), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class Question(Base):
    __tablename__ = 'questions'
    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey('quizzes.id', ondelete='CASCADE'), index=True)
    text: Mapped[str] = mapped_column(Text)
    time_limit_seconds: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)

class Alternative(Base):
    __tablename__ = 'alternatives'
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey('questions.id', ondelete='CASCADE'), index=True)
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer)

class Session(Base):
    __tablename__ = 'sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey('quizzes.id'))
    teacher_id: Mapped[int] = mapped_column(ForeignKey('teachers.id'), index=True)
    quiz_title: Mapped[str] = mapped_column(String(180))
    access_code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default='WAITING')
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    current_position: Mapped[int] = mapped_column(Integer, default=0)
    countdown_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_remaining_ms: Mapped[int | None] = mapped_column(Integer)
    auto_advance_seconds: Mapped[int | None] = mapped_column(Integer)
    require_identifier: Mapped[bool] = mapped_column(Boolean, default=False)
    show_ranking: Mapped[bool] = mapped_column(Boolean, default=True)

class SessionQuestion(Base):
    __tablename__ = 'session_questions'
    __table_args__ = (UniqueConstraint('session_id', 'position'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    time_limit_seconds: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='PENDING')
    preview_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_paused_ms: Mapped[int] = mapped_column(Integer, default=0)

class SessionAlternative(Base):
    __tablename__ = 'session_alternatives'
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey('session_questions.id', ondelete='CASCADE'), index=True)
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer)

class Participant(Base):
    __tablename__ = 'participants'
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    identifier: Mapped[str | None] = mapped_column(String(120))
    reconnect_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Response(Base):
    __tablename__ = 'responses'
    __table_args__ = (UniqueConstraint('participant_id', 'question_id'), Index('ix_responses_session', 'session_id'))
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('sessions.id', ondelete='CASCADE'))
    participant_id: Mapped[int] = mapped_column(ForeignKey('participants.id', ondelete='CASCADE'))
    question_id: Mapped[int] = mapped_column(ForeignKey('session_questions.id', ondelete='CASCADE'))
    alternative_id: Mapped[int] = mapped_column(ForeignKey('session_alternatives.id'))
    is_correct: Mapped[bool] = mapped_column(Boolean)
    response_time_ms: Mapped[int] = mapped_column(Integer)
    points_earned: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
