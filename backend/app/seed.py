"""Run after migrations to create a demonstration teacher and a five-question quiz."""
import os
from .db import SessionLocal
from .models import Teacher, Quiz, Question, Alternative
from .security import password_hash

def main():
    email=os.getenv('DEMO_EMAIL','demo@acertou.local')
    password=os.getenv('DEMO_PASSWORD')
    if not password: raise SystemExit('Set DEMO_PASSWORD before running the seed')
    items=[
        ('Qual camada do modelo OSI transmite bits?', ['Aplicação','Transporte','Rede','Física'],3),
        ('Quanto é 7 × 8?', ['54','56','58','64'],1),
        ('Qual planeta é conhecido como planeta vermelho?', ['Vênus','Marte','Júpiter','Mercúrio'],1),
        ('Qual protocolo é orientado a conexão?', ['UDP','TCP','IP','ICMP'],1),
        ('Qual é a capital do Brasil?', ['Salvador','Rio de Janeiro','Brasília','Recife'],2),
    ]
    with SessionLocal() as db:
        teacher=db.query(Teacher).filter_by(email=email).first()
        if not teacher: teacher=Teacher(name='Professor Demo',email=email,password_hash=password_hash.hash(password));db.add(teacher);db.flush()
        if db.query(Quiz).filter_by(teacher_id=teacher.id,title='Quiz de demonstração').first(): return
        quiz=Quiz(teacher_id=teacher.id,title='Quiz de demonstração',description='Cinco perguntas para testar a plataforma')
        db.add(quiz);db.flush()
        for position,(text,options,correct) in enumerate(items,1):
            question=Question(quiz_id=quiz.id,text=text,time_limit_seconds=30,points=100,position=position)
            db.add(question);db.flush()
            for i,option in enumerate(options): db.add(Alternative(question_id=question.id,text=option,is_correct=i==correct,position=i+1))
        db.commit()
        print(f'Demo ready: {email}')

if __name__=='__main__': main()
