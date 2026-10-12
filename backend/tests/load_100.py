"""Run against a live single-process backend: python tests/load_100.py [API_URL]."""
import asyncio
import json
import secrets
import sys
import time
import httpx
import websockets

API=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8000'
WS=API.replace('http','ws',1)

async def main():
    started=time.monotonic()
    async with httpx.AsyncClient(timeout=30) as client:
        email=f'load-{secrets.token_hex(5)}@example.com'
        teacher=(await client.post(f'{API}/auth/register',json={'name':'Load Teacher','email':email,'password':'load-test-pass-123'})).json()
        headers={'Authorization':f"Bearer {teacher['token']}"}
        quiz=(await client.post(f'{API}/quizzes',headers=headers,json={'title':'Load Test','questions':[{'text':'Questão de carga','time_limit_seconds':30,'points':100,'alternatives':[{'text':'A'},{'text':'B'}],'correct_index':0}]})).json()
        session=(await client.post(f"{API}/quizzes/{quiz['id']}/sessions",headers=headers,json={})).json()
        sid=session['id'];code=session['code']
        async def join(i):
            response=await client.post(f'{API}/sessions/join',json={'code':code,'name':f'Participante {i}'})
            response.raise_for_status()
            return response.json()['token']
        tokens=await asyncio.gather(*(join(i) for i in range(100)))
        async def connect(token):
            socket=await websockets.connect(f'{WS}/ws/sessions/{sid}?role=participant',subprotocols=['acertou',token],max_size=2**20)
            while True:
                event=json.loads(await socket.recv())
                if event['event']=='state': return socket
        sockets=await asyncio.gather(*(connect(token) for token in tokens))
        state=(await client.get(f'{API}/sessions/{sid}',headers=headers)).json()
        assert state['connected_count']==100,state['connected_count']
        await client.post(f'{API}/sessions/{sid}/start',headers=headers)
        async def question(socket):
            while True:
                event=json.loads(await socket.recv())
                if event['event']=='question_started':
                    return (await client.get(f'{API}/sessions/{sid}/participant',headers={'X-Participant-Token':tokens[sockets.index(socket)]})).json()['question']['ends_at']
        deadlines=await asyncio.wait_for(asyncio.gather(*(question(s) for s in sockets)),timeout=25)
        assert len(set(deadlines))==1
        print(f'PASS: 100 simultaneous WebSockets, shared question deadline, {time.monotonic()-started:.1f}s total')
        await asyncio.gather(*(socket.close() for socket in sockets))
        await client.post(f'{API}/sessions/{sid}/finish',headers=headers)

if __name__=='__main__': asyncio.run(main())
