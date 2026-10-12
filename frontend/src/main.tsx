import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, CirclePlus, Copy, Download, LogOut, Play, Users, X } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { API, del, get, participantToken, post, put, request, teacherToken, wsUrl } from './api'
import type { Quiz, QuizQuestion, Report, State } from './types'
import './style.css'

function useLive(id: number, role: 'teacher' | 'participant') {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true, socket: WebSocket, retry: ReturnType<typeof setTimeout>, refreshTimer: ReturnType<typeof setTimeout>
    const token = role === 'teacher' ? teacherToken() : participantToken(id)
    const refresh = () => get<State>(role === 'teacher' ? `/sessions/${id}` : `/sessions/${id}/participant`, role === 'teacher' ? token : '').then(setState).catch(e => { if (role === 'teacher') setError(e.message) })
    const refreshParticipant = () => request<State>(`/sessions/${id}/participant`, { headers: { 'X-Participant-Token': token } }).then(setState).catch(e => setError(e.message))
    const sync = role === 'teacher' ? refresh : refreshParticipant
    const connect = () => {
      if (!active) return
      socket = new WebSocket(`${wsUrl}/ws/sessions/${id}?role=${role}`, ['acertou', token])
      socket.onmessage = e => { const message = JSON.parse(e.data); if (message.event === 'state') setState(message.data); else { clearTimeout(refreshTimer); refreshTimer = setTimeout(sync, 100) } }
      socket.onclose = () => { if (active) retry = setTimeout(connect, 1500) }
      socket.onerror = () => socket.close()
    }
    sync(); connect()
    return () => { active = false; clearTimeout(retry); clearTimeout(refreshTimer); socket?.close() }
  }, [id, role])
  return { state, setState, error }
}

function useClock(state: State | null) {
  const [remaining, setRemaining] = useState(0)
  useEffect(() => {
    const update = () => {
      if (!state) return
      const target = state.status === 'COUNTDOWN' ? state.countdown_ends_at : state.status === 'QUESTION_PREVIEW' ? state.question?.preview_ends_at : state.question?.ends_at
      setRemaining(state.status === 'QUESTION_PAUSED' ? (state.paused_remaining_ms || 0) / 1000 : target ? Math.max(0, (new Date(target).getTime() - Date.now()) / 1000) : 0)
    }
    update(); const timer = setInterval(update, 150); return () => clearInterval(timer)
  }, [state])
  return remaining
}

function Header({ teacher = false }: { teacher?: boolean }) {
  const nav = useNavigate()
  return <header className="top"><Link className="brand" to="/">✦ Acertou<span>.</span></Link><nav>{teacher ? <><Link to="/dashboard">Painel</Link><Link to="/quizzes">Quizzes</Link><Link to="/historico">Histórico</Link><button className="plain" onClick={() => { localStorage.removeItem('teacher_token'); nav('/login') }}><LogOut size={17} /> Sair</button></> : <><Link to="/entrar">Participar</Link><Link to="/login">Sou professor</Link></>}</nav></header>
}

function Auth({ register = false }: { register?: boolean }) {
  const nav = useNavigate(); const [name, setName] = useState(''); const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) { e.preventDefault(); setBusy(true); setError(''); try { const result = await request<{ token: string }>(`/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify({ name, email, password }) }); localStorage.setItem('teacher_token', result.token); nav('/dashboard') } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  return <><Header /><main className="auth-wrap"><div className="auth-art"><div className="eyebrow">PARA QUEM ENSINA</div><h1>Transforme cada pergunta em uma descoberta.</h1><p>Crie quizzes, acompanhe sua turma ao vivo e saiba exatamente onde cada aluno precisa de ajuda.</p><div className="floating-card"><span className="big-check">✓</span><div><strong>Aprendizado visível</strong><small>Resultados por aluno e por questão</small></div></div></div><form className="card auth-card" onSubmit={submit}><span className="eyebrow">ACESSO DO PROFESSOR</span><h2>{register ? 'Criar sua conta' : 'Boas-vindas de volta'}</h2><p>Comece em poucos passos.</p>{register && <label>Seu nome<input required minLength={2} value={name} onChange={e => setName(e.target.value)} placeholder="Ana Oliveira" /></label>}<label>E-mail<input required type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="voce@escola.com" /></label><label>Senha<input required type="password" minLength={register ? 10 : 1} value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••••" /></label>{error && <div className="error" role="alert">{error}</div>}<button className="primary full" disabled={busy}>{busy ? 'Aguarde...' : register ? 'Criar conta' : 'Entrar'} <ArrowRight size={18} /></button><p className="switch">{register ? 'Já tem conta?' : 'Ainda não tem conta?'} <Link to={register ? '/login' : '/cadastro'}>{register ? 'Entrar' : 'Cadastre-se'}</Link></p></form></main></>
}

function Landing() { return <><Header /><main className="hero"><span className="eyebrow">QUIZZES QUE CONECTAM</span><h1>Uma sala inteira.<br /><em>Todo mundo participa.</em></h1><p>Crie perguntas, jogue em tempo real e enxergue o aprendizado de cada estudante.</p><div className="hero-actions"><Link className="primary" to="/entrar">Entrar em um quiz <ArrowRight size={18}/></Link><Link className="secondary" to="/cadastro">Criar meu quiz</Link></div><div className="hero-graphic"><div className="sample-question"><span>QUESTÃO 02 / 05</span><strong>Qual alternativa está correta?</strong><div><i>A</i> Uma resposta possível</div><div className="selected"><i>B</i> A resposta certa <Check size={20}/></div><div><i>C</i> Outra possibilidade</div></div><div className="stat-bubble"><strong>82%</strong><small>da turma acertou</small></div></div></main></> }

function Dashboard() { const [quizzes, setQuizzes] = useState<Quiz[]>([]); const [sessions, setSessions] = useState<State[]>([]); const [error, setError] = useState(''); useEffect(() => { get<Quiz[]>('/quizzes').then(setQuizzes).catch(e => setError(e.message)); get<State[]>('/sessions').then(setSessions).catch(e => setError(e.message)) }, []); return <><Header teacher/><main className="container"><div className="page-heading"><div><span className="eyebrow">PAINEL DO PROFESSOR</span><h1>Vamos aprender juntos.</h1><p>Seus quizzes e sessões em um só lugar.</p></div><Link className="primary" to="/quizzes/novo"><CirclePlus size={18}/> Criar quiz</Link></div>{error && <div className="error">{error}</div>}<div className="metrics"><div className="metric"><strong>{quizzes.length}</strong><span>quizzes criados</span></div><div className="metric"><strong>{sessions.filter(s => s.status === 'FINISHED').length}</strong><span>sessões concluídas</span></div><div className="metric"><strong>{sessions.reduce((n,s)=>n+s.participant_count,0)}</strong><span>participações</span></div></div><div className="section-title"><h2>Últimas sessões</h2><Link to="/historico">Ver todas <ArrowRight size={16}/></Link></div><div className="list">{sessions.slice(0,5).map(s => <Link className="list-item" to={s.status === 'FINISHED' ? `/sessoes/${s.id}/resultados` : `/sessoes/${s.id}`} key={s.id}><div><strong>{s.quiz_title}</strong><small>Código {s.code} · {s.participant_count} participantes</small></div><span className="badge">{statusLabel(s.status)}</span><ArrowRight size={18}/></Link>)}{!sessions.length && <div className="empty">Nenhuma sessão ainda. Crie um quiz para começar.</div>}</div></main></> }

const blankQuestion = (): QuizQuestion => ({ text: '', time_limit_seconds: 30, points: 100, alternatives: [{text:''},{text:''},{text:''},{text:''}], correct_index: 0 })
function QuizList() { const [quizzes, setQuizzes] = useState<Quiz[]>([]); const [error, setError] = useState(''); const refresh = () => get<Quiz[]>('/quizzes').then(setQuizzes).catch(e => setError(e.message)); useEffect(() => { refresh() }, []); async function duplicate(id:number) { try { await post(`/quizzes/${id}/duplicate`, {}); refresh() } catch(e) {setError((e as Error).message)} } async function remove(id:number) { if (!confirm('Excluir este quiz?')) return; try { await del(`/quizzes/${id}`); refresh() } catch(e) {setError((e as Error).message)} } return <><Header teacher/><main className="container"><div className="page-heading"><div><span className="eyebrow">BIBLIOTECA</span><h1>Meus quizzes</h1><p>Prepare experiências para sua turma.</p></div><Link className="primary" to="/quizzes/novo"><CirclePlus size={18}/> Criar quiz</Link></div>{error && <div className="error">{error}</div>}<div className="quiz-grid">{quizzes.map(q => <article className="card quiz-card" key={q.id}><div className="quiz-icon">✦</div><h2>{q.title}</h2><p>{q.description || 'Quiz sem descrição'}</p><small>{q.questions.length} questões</small><div className="quiz-actions"><Link className="primary" to={`/quizzes/${q.id}/sessao`}>Iniciar sessão</Link><Link className="secondary" to={`/quizzes/${q.id}/editar`}>Editar</Link></div><div className="minor-actions"><button onClick={() => duplicate(q.id)}>Duplicar</button><button onClick={() => remove(q.id)}>Excluir</button></div></article>)}{!quizzes.length && <div className="empty">Você ainda não criou quizzes.</div>}</div></main></> }

function QuizEditor() { const {id} = useParams(); const nav=useNavigate(); const [title,setTitle]=useState(''); const [description,setDescription]=useState(''); const [items,setItems]=useState<QuizQuestion[]>([blankQuestion()]); const [selected,setSelected]=useState(0); const [preview,setPreview]=useState(false); const [error,setError]=useState(''); const [busy,setBusy]=useState(false); useEffect(() => { if (id) get<Quiz>(`/quizzes/${id}`).then(q => {setTitle(q.title);setDescription(q.description);setItems(q.questions)}).catch(e => setError(e.message)) }, [id]); const item=items[selected]; function change(patch:Partial<QuizQuestion>) {setItems(list => list.map((q,i)=>i===selected?{...q,...patch}:q))} function move(index:number, direction:number) {const target=index+direction;if(target<0||target>=items.length)return;const copy=[...items];[copy[index],copy[target]]=[copy[target],copy[index]];setItems(copy);setSelected(target)} async function save(e:React.FormEvent) {e.preventDefault();setBusy(true);setError('');try {const body={title,description,questions:items}; if (id) await put(`/quizzes/${id}`,body); else await post('/quizzes',body);nav('/quizzes')}catch(e){setError((e as Error).message)}finally{setBusy(false)}} return <><Header teacher/><main className="container editor"><div className="page-heading"><div><Link className="back" to="/quizzes"><ArrowLeft size={16}/> Meus quizzes</Link><h1>{id?'Editar quiz':'Novo quiz'}</h1></div><button className="secondary" type="button" onClick={()=>setPreview(!preview)}>{preview?'Fechar prévia':'Pré-visualizar'}</button></div><form onSubmit={save}><div className="card form-card"><label>Título do quiz<input required maxLength={180} value={title} onChange={e=>setTitle(e.target.value)} placeholder="Ex.: Revisão de Ciências" /></label><label>Descrição opcional<textarea value={description} onChange={e=>setDescription(e.target.value)} placeholder="Sobre o que é este quiz?" /></label></div><div className="editor-layout"><aside className="card question-nav"><h3>Questões</h3>{items.map((q,i)=><div className={`nav-row ${i===selected?'active':''}`} key={i}><button type="button" onClick={()=>setSelected(i)}><span>{String(i+1).padStart(2,'0')}</span> {q.text || 'Nova questão'}</button><button type="button" aria-label="Mover acima" onClick={()=>move(i,-1)}>↑</button><button type="button" aria-label="Mover abaixo" onClick={()=>move(i,1)}>↓</button></div>)}<button className="add-question" type="button" onClick={()=>{setItems([...items,blankQuestion()]);setSelected(items.length)}}><CirclePlus size={16}/> Adicionar questão</button></aside><section className="card question-edit"><div className="question-top"><span className="eyebrow">QUESTÃO {selected+1} DE {items.length}</span>{items.length>1&&<button className="danger-link" type="button" onClick={()=>{setItems(items.filter((_,i)=>i!==selected));setSelected(Math.max(0,selected-1))}}>Remover</button>}</div>{preview?<div className="preview"><h2>{item.text||'Sua pergunta aparecerá aqui'}</h2>{item.alternatives.map((a,i)=><div className="preview-option" key={i}><b>{String.fromCharCode(65+i)}</b>{a.text||`Alternativa ${i+1}`}</div>)}</div>:<><label>Enunciado<textarea required value={item.text} onChange={e=>change({text:e.target.value})} placeholder="Escreva sua pergunta" /></label><div className="options-head"><h3>Alternativas</h3><small>Marque a resposta correta</small></div>{item.alternatives.map((a,i)=><div className="option-edit" key={i}><input type="radio" aria-label={`Resposta correta ${i+1}`} checked={item.correct_index===i} onChange={()=>change({correct_index:i})}/><span>{String.fromCharCode(65+i)}</span><input required value={a.text} onChange={e=>change({alternatives:item.alternatives.map((v,j)=>i===j?{text:e.target.value}:v)})} placeholder={`Alternativa ${i+1}`} />{item.alternatives.length>2&&<button type="button" aria-label="Remover alternativa" onClick={()=>change({alternatives:item.alternatives.filter((_,j)=>j!==i),correct_index:item.correct_index===i?0:item.correct_index>i?item.correct_index-1:item.correct_index})}><X size={16}/></button>}</div>)}{item.alternatives.length<6&&<button type="button" className="add-question" onClick={()=>change({alternatives:[...item.alternatives,{text:''}]})}>+ Adicionar alternativa</button>}<div className="settings"><label>Tempo (segundos)<input type="number" min="5" max="300" value={item.time_limit_seconds} onChange={e=>change({time_limit_seconds:Number(e.target.value)})}/></label><label>Pontos<input type="number" min="0" max="10000" value={item.points} onChange={e=>change({points:Number(e.target.value)})}/></label></div></>}</section></div>{error&&<div className="error" role="alert">{error}</div>}<div className="editor-footer"><button className="primary" disabled={busy}>{busy?'Salvando...':'Salvar quiz'} <ArrowRight size={17}/></button></div></form></main></> }

function SessionSetup() { const {id}=useParams();const nav=useNavigate();const [quiz,setQuiz]=useState<Quiz|null>(null);const [scheduled,setScheduled]=useState('');const [auto,setAuto]=useState('');const [identifier,setIdentifier]=useState(false);const [ranking,setRanking]=useState(true);const [error,setError]=useState('');useEffect(()=>{get<Quiz>(`/quizzes/${id}`).then(setQuiz).catch(e=>setError(e.message))},[id]);async function create(e:React.FormEvent){e.preventDefault();try{const state=await post<State>(`/quizzes/${id}/sessions`,{scheduled_start_at:scheduled?new Date(scheduled).toISOString():null,auto_advance_seconds:auto?Number(auto):null,require_identifier:identifier,show_ranking:ranking});nav(`/sessoes/${state.id}`)}catch(e){setError((e as Error).message)}}return <><Header teacher/><main className="container narrow"><Link className="back" to="/quizzes"><ArrowLeft size={16}/> Meus quizzes</Link><div className="page-heading"><div><span className="eyebrow">NOVA SESSÃO</span><h1>Prepare sua turma.</h1><p>{quiz?.title}</p></div></div><form className="card setup-card" onSubmit={create}><h2>Configurações da sessão</h2><label>Início agendado (opcional)<input type="datetime-local" value={scheduled} onChange={e=>setScheduled(e.target.value)}/><small>Deixe vazio para começar manualmente.</small></label><label>Avanço automático (opcional)<select value={auto} onChange={e=>setAuto(e.target.value)}><option value="">Professor controla</option><option value="5">Após 5 segundos</option><option value="10">Após 10 segundos</option><option value="20">Após 20 segundos</option></select></label><label className="checkline"><input type="checkbox" checked={identifier} onChange={e=>setIdentifier(e.target.checked)}/> Exigir matrícula ou identificador</label><label className="checkline"><input type="checkbox" checked={ranking} onChange={e=>setRanking(e.target.checked)}/> Mostrar ranking final aos alunos</label>{error&&<div className="error">{error}</div>}<button className="primary">Criar sala <ArrowRight size={18}/></button></form></main></>}

const statusLabel=(s:string)=>({WAITING:'Aguardando',COUNTDOWN:'Contagem regressiva',QUESTION_PREVIEW:'Leitura do enunciado',QUESTION_ACTIVE:'Questão aberta',QUESTION_PAUSED:'Pausada',SHOWING_RESULTS:'Resultados',FINISHED:'Concluída',CANCELLED:'Cancelada'}[s]||s)
function Podium({ students }: { students: Report['students'] }) {
  const top = students.slice(0, 3)
  if (!top.length) return <div className="card podium-empty"><h2>Quiz concluído!</h2><p>Nenhum estudante participou desta sessão.</p></div>
  return <section className="card podium-panel" aria-label="Pódio da sessão">
    <span className="eyebrow">RESULTADO FINAL</span>
    <h2>O pódio da turma</h2>
    <p>Parabéns a todos que participaram!</p>
    <div className="podium-places">
      {[top[1], top[0], top[2]].map((student, index) => student
        ? <div className={`podium-place place-${student.rank}`} key={student.id}>
            <div className="podium-medal" aria-hidden="true">{['🥈','🥇','🥉'][index]}</div>
            <strong>{student.name}</strong>
            <span>{student.rank}º lugar</span>
            <b>{student.total_score} pontos</b>
            <small>{student.correct_answers} acertos</small>
          </div>
        : <div className="podium-placeholder" key={index} />)}
    </div>
  </section>
}

function SessionRoom() {
  const { id } = useParams()
  const sessionId = Number(id)
  const { state, setState, error: liveError } = useLive(sessionId, 'teacher')
  const remaining = useClock(state)
  const [error, setError] = useState('')
  const [finalReport, setFinalReport] = useState<Report | null>(null)

  useEffect(() => {
    if (state?.status === 'FINISHED') get<Report>(`/sessions/${sessionId}/results`).then(setFinalReport).catch(e => setError(e.message))
  }, [state?.status, sessionId])

  async function action(name: string) {
    setError('')
    try { setState(await post<State>(`/sessions/${sessionId}/${name}`, {})) }
    catch (e) { setError((e as Error).message) }
  }

  if (!state) return <><Header teacher/><main className="container"><p>{liveError || 'Carregando sessão...'}</p></main></>
  const link = `${location.origin}/entrar/${state.code}`
  const question = state.question
  const preview = state.status === 'QUESTION_PREVIEW'
  const active = state.status === 'QUESTION_ACTIVE'
  const paused = state.status === 'QUESTION_PAUSED'
  const timerTotal = preview ? question?.preview_seconds || 5 : question?.time_limit_seconds || 1

  return <><Header teacher/><main className="container">
    <Link className="back" to="/historico"><ArrowLeft size={16}/> Histórico</Link>
    <div className="page-heading"><div>
      <span className="eyebrow">SESSÃO AO VIVO · {statusLabel(state.status).toUpperCase()}</span>
      <h1>{state.quiz_title}</h1>
      <p>{state.total_questions} questões · {state.connected_count} conectados · {state.participant_count} inscritos</p>
    </div><Link className="secondary" to={`/sessoes/${sessionId}/resultados`}>Ver resultados</Link></div>
    {error && <div className="error" role="alert">{error}</div>}
    {state.status === 'WAITING' ? <div className="room-grid">
      <div className="card join-card"><span className="eyebrow">CÓDIGO DA SALA</span><strong className="room-code">{state.code}</strong>
        <p>Compartilhe com seus alunos</p><div className="link-row"><span>{link}</span><button aria-label="Copiar link" onClick={() => navigator.clipboard.writeText(link)}><Copy size={18}/></button></div>
        <QRCodeSVG value={link} size={150} marginSize={2}/>
        {state.scheduled_start_at && <p>Início programado: {new Date(state.scheduled_start_at).toLocaleString('pt-BR')}</p>}
        <div className="room-controls"><button className="primary" onClick={() => action('start')}><Play size={18}/> Iniciar quiz</button><button className="danger-link" onClick={() => action('cancel')}>Cancelar sessão</button></div>
      </div>
      <div className="card participants-card"><h2><Users size={20}/> Participantes conectados ({state.connected_count})</h2>
        {state.participants?.map(p => <div className="participant-row" key={p.id}><span className="avatar">{p.name[0]?.toUpperCase()}</span><div><strong>{p.name}</strong><small>{p.identifier}{p.connected ? ' · Conectado' : ' · Desconectado'}</small></div></div>)}
        {!state.participants?.length && <p>Aguardando os primeiros alunos...</p>}
      </div>
    </div> : state.status === 'FINISHED' ? <>
      {finalReport ? <Podium students={finalReport.students}/> : <div className="card podium-empty"><h2>Quiz concluído!</h2><p>Preparando o pódio...</p></div>}
      <div className="podium-actions"><Link className="primary" to={`/sessoes/${sessionId}/resultados`}>Ver relatório completo <ArrowRight size={18}/></Link></div>
    </> : <div className="presentation">
      <div className="card presentation-card">
        <div className="presentation-head"><span className="eyebrow">{state.status === 'COUNTDOWN' ? 'PREPARE-SE' : `QUESTÃO ${state.current_position} DE ${state.total_questions}`}</span><span className="badge">{statusLabel(state.status)}</span></div>
        {state.status === 'COUNTDOWN' ? <div className="countdown">{Math.ceil(remaining)}</div> : question ? <>
          {preview && <p className="preview-caption">Leia o enunciado. As alternativas aparecem em {Math.ceil(remaining)}s.</p>}
          {(preview || active || paused) && <div className="timer"><strong>{paused ? 'Pausado' : `${Math.ceil(remaining)}s`}</strong><div className="progress"><span style={{width: `${Math.min(100, remaining / timerTotal * 100)}%`}}/></div></div>}
          <h2>{question.text}</h2>
          {!preview && <div className="present-options">{question.alternatives.map(a => <div className={question.correct_alternative_id === a.id && state.status === 'SHOWING_RESULTS' ? 'correct' : ''} key={a.id}><b>{String.fromCharCode(64 + a.position)}</b>{a.text}</div>)}</div>}
          {state.status === 'SHOWING_RESULTS' && <p className="results-caption">Tempo encerrado. A resposta correta está destacada.</p>}
        </> : <h2>Sessão {statusLabel(state.status).toLowerCase()}</h2>}
        <div className="room-controls">
          {active && <button className="secondary" onClick={() => action('pause')}>Pausar</button>}
          {paused && <button className="primary" onClick={() => action('resume')}>Retomar</button>}
          {state.status === 'SHOWING_RESULTS' && <button className="primary" onClick={() => action('next')}>{state.current_position === state.total_questions ? 'Concluir quiz' : 'Próxima questão'} <ArrowRight size={18}/></button>}
          {!['FINISHED','CANCELLED'].includes(state.status) && <button className="danger-link" onClick={() => action('finish')}>Encerrar quiz</button>}
        </div>
      </div>
      <div className="card side-panel"><h3>Turma conectada</h3><strong>{state.connected_count}</strong><p>participantes conectados</p><Link to={`/sessoes/${sessionId}/resultados`}>Abrir análise <ArrowRight size={16}/></Link></div>
    </div>}
  </main></>
}

function Join({prefill}: {prefill?:string}) {const nav=useNavigate();const [code,setCode]=useState(prefill||'');const [name,setName]=useState('');const [identifier,setIdentifier]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{const result=await request<{token:string;session_id:number}>('/sessions/join',{method:'POST',body:JSON.stringify({code,name,identifier:identifier||null})});localStorage.setItem(`participant_${result.session_id}`,result.token);nav(`/jogar/${result.session_id}`)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}return <><Header/><main className="join-wrap"><div className="join-intro"><span className="eyebrow">HORA DE PARTICIPAR</span><h1>Pronto para jogar?</h1><p>Digite o código da sala e conte pra gente quem é você.</p></div><form className="card join-form" onSubmit={submit}><label>Código da sessão<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,''))} placeholder="000000" className="code-input"/></label><label>Seu nome<input required value={name} onChange={e=>setName(e.target.value)} placeholder="Como podemos chamar você?"/></label><label>Matrícula (se solicitada)<input value={identifier} onChange={e=>setIdentifier(e.target.value)} placeholder="Opcional"/></label>{error&&<div className="error" role="alert">{error}</div>}<button className="primary full" disabled={busy}>{busy?'Entrando...':'Entrar na sala'} <ArrowRight size={18}/></button></form></main></>}
function JoinCode(){const {code}=useParams();return <Join prefill={code}/>}

function PlayRoom() {
  const { id } = useParams()
  const sessionId = Number(id)
  const { state, setState, error: liveError } = useLive(sessionId, 'participant')
  const remaining = useClock(state)
  const [error, setError] = useState('')
  const [ranking, setRanking] = useState<{name: string; score: number; rank: number}[]>([])

  useEffect(() => {
    if (state?.status === 'FINISHED' && state.show_ranking)
      request<{name: string; score: number; rank: number}[]>(`/sessions/${sessionId}/ranking`, {headers: {'X-Participant-Token': participantToken(sessionId)}}).then(setRanking).catch(() => {})
  }, [state?.status, state?.show_ranking, sessionId])

  async function answer(alternative_id: number) {
    setError('')
    try {
      const result = await request<{alternative_id: number}>(`/sessions/${sessionId}/answer`, {
        method: 'POST', headers: {'X-Participant-Token': participantToken(sessionId)},
        body: JSON.stringify({alternative_id})
      })
      setState(current => {
        if (!current?.participant || current.question?.id !== state?.question?.id || current.status !== 'QUESTION_ACTIVE') return current
        return {...current, participant: {...current.participant, answer: {alternative_id: result.alternative_id}}}
      })
    } catch (e) { setError((e as Error).message) }
  }

  if (!state) return <><Header/><main className="player"><p>{liveError || 'Conectando à sala...'}</p></main></>
  const q = state.question
  const mine = state.participant
  const preview = state.status === 'QUESTION_PREVIEW'
  const active = state.status === 'QUESTION_ACTIVE'
  const paused = state.status === 'QUESTION_PAUSED'
  const results = state.status === 'SHOWING_RESULTS'

  return <><Header/><main className="player">
    <div className="player-top"><span className="eyebrow">{state.quiz_title}</span><span>{mine?.name} · {mine?.score || 0} pts</span></div>
    {state.status === 'WAITING' ? <div className="player-center"><div className="waiting-icon">✦</div><span className="eyebrow">VOCÊ ENTROU NA SESSÃO</span><h1>Agora é só aguardar.</h1><p>O professor vai iniciar em breve.</p><div className="waiting-info"><span>Código <strong>{state.code}</strong></span><span>Conectados <strong>{state.connected_count}</strong></span></div></div>
    : state.status === 'COUNTDOWN' ? <div className="player-center"><h1>Prepare-se!</h1><div className="countdown">{Math.ceil(remaining)}</div></div>
    : state.status === 'FINISHED' ? <div className="player-center"><div className="waiting-icon">✓</div><h1>Quiz concluído!</h1><p>Você acertou {mine?.correct}/{state.total_questions} questões.</p><strong className="final-score">{mine?.score} pontos</strong><p>Aproveitamento: {Math.round((mine?.correct || 0) / state.total_questions * 100)}%</p>{ranking.length > 0 && <div className="ranking"><h2>Ranking</h2>{ranking.map(p => <div key={p.rank}><span>{p.rank}º {p.name}</span><strong>{p.score} pts</strong></div>)}</div>}</div>
    : state.status === 'CANCELLED' ? <div className="player-center"><h1>Sessão cancelada</h1></div>
    : q ? <div className="play-question">
      <div className="question-meta"><span>QUESTÃO {q.number} / {state.total_questions}</span><strong>{paused ? 'Pausado' : results ? 'Tempo encerrado' : `${Math.ceil(remaining)}s`}</strong></div>
      {(preview || active || paused) && <div className="progress"><span style={{width: `${Math.min(100, remaining / (preview ? q.preview_seconds : q.time_limit_seconds) * 100)}%`}}/></div>}
      {preview && <p className="preview-caption">Leia o enunciado. As alternativas aparecem em {Math.ceil(remaining)}s.</p>}
      <h1>{q.text}</h1>
      {!preview && <div className="answer-options">{q.alternatives.map(a => <button key={a.id} disabled={!!mine?.answer || !active || remaining <= 0} className={`${mine?.answer?.alternative_id === a.id ? 'chosen' : ''} ${results && q.correct_alternative_id === a.id ? 'correct' : ''}`} onClick={() => answer(a.id)}><b>{String.fromCharCode(64 + a.position)}</b>{a.text}</button>)}</div>}
      {results ? mine?.answer?.is_correct === true
        ? <div className="feedback success">✓ Resposta correta! · +{mine.answer.points_earned} pontos</div>
        : mine?.answer?.is_correct === false
          ? <div className="feedback failure">✕ Resposta incorreta · +0 pontos</div>
          : <div className="feedback">Tempo esgotado · Sem resposta</div>
      : mine?.answer ? <div className="feedback">Resposta registrada. O resultado aparece ao fim do tempo.</div>
      : paused ? <div className="feedback">Questão pausada pelo professor</div> : null}
      {error && <div className="error" role="alert">{error}</div>}
      {results && <p className="next-note">Aguardando a próxima questão...</p>}
    </div>
    : <div className="player-center"><h1>Aguardando...</h1></div>}
  </main></>
}

function History(){const [sessions,setSessions]=useState<State[]>([]);const [error,setError]=useState('');const refresh=()=>get<State[]>('/sessions').then(setSessions).catch(e=>setError(e.message));useEffect(() => { refresh() },[]);async function remove(id:number){if(!confirm('Excluir permanentemente todos os dados desta sessão?'))return;try{await del(`/sessions/${id}`);refresh()}catch(e){setError((e as Error).message)}}return <><Header teacher/><main className="container"><div className="page-heading"><div><span className="eyebrow">SUAS TURMAS</span><h1>Histórico de sessões</h1><p>Consulte apresentações passadas e em andamento.</p></div></div>{error&&<div className="error">{error}</div>}<div className="list">{sessions.map(s=><div className="list-item" key={s.id}><div><strong>{s.quiz_title}</strong><small>Código {s.code} · {s.participant_count} participantes</small></div><span className="badge">{statusLabel(s.status)}</span><Link className="secondary" to={`/sessoes/${s.id}`}>Abrir</Link><Link className="secondary" to={`/sessoes/${s.id}/resultados`}>Resultados</Link>{['FINISHED','CANCELLED'].includes(s.status)&&<button className="danger-link" onClick={()=>remove(s.id)}>Excluir dados</button>}</div>)}{!sessions.length&&<div className="empty">Nenhuma sessão registrada.</div>}</div></main></>}

function Results(){const {id}=useParams();const [data,setData]=useState<Report|null>(null);const [student,setStudent]=useState<number|null>(null);const [question,setQuestion]=useState<number|null>(null);const [error,setError]=useState('');useEffect(()=>{get<Report>(`/sessions/${id}/results`).then(setData).catch(e=>setError(e.message))},[id]);async function download(kind:string){try{const response=await fetch(`${API}/sessions/${id}/export/${kind}`,{headers:{Authorization:`Bearer ${teacherToken()}`}});if(!response.ok)throw new Error('Falha no download');const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`acertou-${id}-${kind}.csv`;a.click();URL.revokeObjectURL(url)}catch(e){setError((e as Error).message)}}if(!data)return <><Header teacher/><main className="container">{error||'Carregando resultados...'}</main></>;const chosen=data.students.find(s=>s.id===student);const selectedQuestion=data.questions.find(q=>q.number===question);return <><Header teacher/><main className="container results"><Link className="back" to={`/sessoes/${id}`}><ArrowLeft size={16}/> Sessão</Link><div className="page-heading"><div><span className="eyebrow">ANÁLISE DA TURMA</span><h1>{data.quiz_title}</h1><p>{new Date(data.session_date).toLocaleString('pt-BR')}</p></div><div className="export-buttons"><button className="secondary" onClick={()=>download('summary')}><Download size={16}/> Resumo CSV</button><button className="secondary" onClick={()=>download('detailed')}><Download size={16}/> Detalhado CSV</button><button className="secondary" onClick={()=>download('matrix')}><Download size={16}/> Matriz CSV</button></div></div>{error&&<div className="error">{error}</div>}<div className="metrics results-metrics"><div className="metric"><strong>{data.summary.participants}</strong><span>participantes</span></div><div className="metric"><strong>{data.summary.average_accuracy_percentage}%</strong><span>média de acertos</span></div><div className="metric"><strong>{data.summary.correct}</strong><span>acertos</span></div><div className="metric"><strong>{data.summary.incorrect}</strong><span>erros</span></div><div className="metric"><strong>{data.summary.unanswered}</strong><span>sem resposta</span></div></div><div className="section-title"><h2>Desempenho por aluno</h2><small>Selecione um aluno para ver os detalhes.</small></div><div className="card table-wrap"><table><thead><tr><th>Aluno</th>{data.questions.map(q=><th key={q.number}>Q{q.number}</th>)}<th>Acertos</th><th>Pontos</th></tr></thead><tbody>{data.students.map(s=><tr key={s.id} onClick={()=>setStudent(s.id)} tabIndex={0} onKeyDown={e=>e.key==='Enter'&&setStudent(s.id)}><td><strong>{s.name}</strong><small>{s.identifier}</small></td>{s.details.map((d,i)=><td key={i} aria-label={d.result} className={`cell-${d.result}`}>{d.result==='CORRECT'?'✓':d.result==='INCORRECT'?'✕':'—'}</td>)}<td>{s.correct_answers}/{s.total_questions}</td><td><strong>{s.total_score}</strong></td></tr>)}</tbody></table></div>{chosen&&<div className="card detail-panel"><div className="detail-head"><div><span className="eyebrow">DETALHE DO ESTUDANTE</span><h2>{chosen.name}</h2><p>{chosen.correct_answers} acertos · {chosen.wrong_answers} erros · {chosen.unanswered_questions} sem resposta · {chosen.total_score} pontos</p></div><button aria-label="Fechar detalhes" onClick={()=>setStudent(null)}><X/></button></div>{chosen.details.map(d=><div className="detail-row" key={d.question_number}><strong>Q{d.question_number}. {d.question_text}</strong><span className={`result-${d.result}`}>{d.result==='CORRECT'?'Correta':d.result==='INCORRECT'?'Incorreta':'Não respondeu'}</span><p>Marcada: {d.selected_option_text||'—'} · Correta: {d.correct_option_text}</p><small>Tempo: {d.response_time_seconds==null?'—':`${d.response_time_seconds}s`} · Pontos: {d.points_earned}</small></div>)}</div>}<div className="section-title"><h2>Análise por questão</h2><small>Veja a distribuição das alternativas.</small></div><div className="question-tabs">{data.questions.map(q=><button className={question===q.number?'active':''} onClick={()=>setQuestion(q.number)} key={q.number}>Questão {q.number}</button>)}</div>{selectedQuestion&&<div className="card analysis-card"><h3>{selectedQuestion.text}</h3><p>{selectedQuestion.accuracy_percentage}% da turma acertou</p>{selectedQuestion.distribution.map(a=><div className="bar-row" key={a.position}><span>{String.fromCharCode(64+a.position)}. {a.text}{a.is_correct?' ✓':''}</span><div className="bar"><i style={{width:`${data.summary.participants?Math.max(2,a.count/data.summary.participants*100):0}%`}}/></div><strong>{a.count}</strong></div>)}<div className="analysis-names"><p><strong>Acertaram:</strong> {selectedQuestion.correct.join(', ')||'—'}</p><p><strong>Erraram:</strong> {selectedQuestion.incorrect.join(', ')||'—'}</p><p><strong>Não responderam:</strong> {selectedQuestion.unanswered.join(', ')||'—'}</p></div></div>}</main></>}

function Protected({children}:{children:React.ReactNode}){return teacherToken()?<>{children}</>:<Navigate to="/login" replace/>}
function App(){return <BrowserRouter><Routes><Route path="/" element={<Landing/>}/><Route path="/login" element={<Auth/>}/><Route path="/cadastro" element={<Auth register/>}/><Route path="/entrar" element={<Join/>}/><Route path="/entrar/:code" element={<JoinCode/>}/><Route path="/jogar/:id" element={<PlayRoom/>}/><Route path="/dashboard" element={<Protected><Dashboard/></Protected>}/><Route path="/quizzes" element={<Protected><QuizList/></Protected>}/><Route path="/quizzes/novo" element={<Protected><QuizEditor/></Protected>}/><Route path="/quizzes/:id/editar" element={<Protected><QuizEditor/></Protected>}/><Route path="/quizzes/:id/sessao" element={<Protected><SessionSetup/></Protected>}/><Route path="/sessoes/:id" element={<Protected><SessionRoom/></Protected>}/><Route path="/sessoes/:id/resultados" element={<Protected><Results/></Protected>}/><Route path="/historico" element={<Protected><History/></Protected>}/></Routes></BrowserRouter>}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
