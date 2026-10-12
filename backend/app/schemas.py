from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, model_validator

class Register(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class Login(BaseModel):
    email: EmailStr
    password: str

class AlternativeIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)

class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    time_limit_seconds: int = Field(ge=5, le=300)
    points: int = Field(ge=0, le=10000)
    alternatives: list[AlternativeIn] = Field(min_length=2, max_length=6)
    correct_index: int

    @model_validator(mode='after')
    def valid_correct(self):
        if self.correct_index < 0 or self.correct_index >= len(self.alternatives):
            raise ValueError('Resposta correta inválida')
        return self

class QuizIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default='', max_length=5000)
    questions: list[QuestionIn] = Field(min_length=1, max_length=100)

class SessionIn(BaseModel):
    scheduled_start_at: datetime | None = None
    auto_advance_seconds: int | None = Field(default=None, ge=2, le=60)
    require_identifier: bool = False
    show_ranking: bool = True

class JoinIn(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')
    name: str = Field(min_length=1, max_length=120)
    identifier: str | None = Field(default=None, max_length=120)

class AnswerIn(BaseModel):
    alternative_id: int
