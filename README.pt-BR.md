# Acertou

**Português** · [English](README.md)

Plataforma de quizzes ao vivo para professores e estudantes. Professores criam quizzes e controlam sessões; estudantes entram com código e nome, sem conta. Respostas, estado das sessões e relatórios ficam no banco de dados.

Cada questão começa com **5 segundos apenas de enunciado**. Depois, as alternativas aparecem pelo tempo configurado no quiz. O servidor guarda os dois prazos. Ao enviar uma resposta, o aluno vê apenas que ela foi registrada; acerto, pontos e alternativa correta são revelados quando o tempo da questão termina. Ao concluir, o professor vê o pódio dos três primeiros colocados na tela da sessão.

## Estrutura

- `frontend/`: React, TypeScript, Vite, CSS responsivo, WebSocket e testes Playwright.
- `backend/app/`: API FastAPI, modelos SQLAlchemy, autenticação, temporizador, WebSocket, relatórios e CSV.
- `backend/migrations/`: migração Alembic inicial.
- `backend/tests/`: fluxo integrado com três participantes e cinco questões.
- `docker-compose.yml`: frontend, backend e PostgreSQL.

## Usar no seu PC e compartilhar temporariamente na internet

O Docker executa frontend, API e PostgreSQL no seu PC. Um [Quick Tunnel da Cloudflare](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) fornece um endereço HTTPS público temporário, sem abrir portas no roteador e sem precisar de conta Cloudflare. O link muda quando o túnel é recriado e funciona enquanto o PC, o Docker e o túnel estiverem ligados. É uma opção para aulas e testes, sem garantia de disponibilidade. A Cloudflare limita esse tipo de túnel a 200 requisições simultâneas; conexões WebSocket permanecem abertas durante a aula.

### 1. Preparação, uma vez só

No Ubuntu 24.04 com `docker.io`, instale Compose v2 e Buildx se ainda não estiverem disponíveis:

```bash
sudo apt update
sudo apt install docker-compose-v2 docker-buildx openssl
docker compose version
docker buildx version
```

Na pasta do projeto, crie a configuração. Se você já tem `.env`, preserve o arquivo e confira se `SECRET_KEY` contém um segredo longo. **Não troque `SECRET_KEY` entre aulas**, pois os logins existentes deixam de funcionar.

```bash
cd ~/Acertou
cp -n .env.example .env
if grep -q '^SECRET_KEY=replace-with-a-long-random-secret$' .env; then
  sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
fi
```

O comando gera `SECRET_KEY` se o arquivo ainda contém o valor de exemplo. Se você já configurou outro valor, ele é preservado. O PostgreSQL e os quizzes permanecem no volume `postgres_data` entre usos.

### 2. Iniciar a aula

Execute estes comandos na pasta do projeto:

```bash
cd ~/Acertou
docker compose --profile public up --build -d
docker compose logs -f tunnel
```

Aguarde aparecer nos logs um endereço como `https://algum-nome.trycloudflare.com`. Esse é o endereço para o professor e os alunos, inclusive nos celulares. O QR code da sessão usa o mesmo endereço público. Pressione `Ctrl+C` para sair da visualização dos logs; os contêineres continuam ligados. Abra o link e faça login ou crie sua conta de professor. Para verificar o estado dos contêineres:

```bash
docker compose --profile public ps
```

O site também fica disponível somente no seu PC em `http://localhost:5173`; a documentação da API fica em `http://localhost:8000/docs`. O backend aplica `alembic upgrade head` ao iniciar. As portas locais são vinculadas a `127.0.0.1`, e o túnel publica apenas o site, que encaminha internamente API e WebSocket.

### 3. Encerrar a aula

```bash
cd ~/Acertou
docker compose --profile public down
```

Isso fecha o link público e para os contêineres. O comando mantém o volume do PostgreSQL; **não use `down -v`** se quiser conservar quizzes, contas e resultados. Na próxima aula, repita os comandos da etapa 2 e compartilhe o novo link. Qualquer pessoa com o link pode abrir a página e criar uma conta de professor, pois o cadastro é público. Use uma senha forte, compartilhe o endereço só com a turma e evite inserir matrículas ou outros dados sensíveis até reforçar o controle de acesso.

Para incluir um quiz demonstrativo com cinco questões:

```bash
docker compose exec -e DEMO_PASSWORD='uma-senha-forte' backend python -m app.seed
```

Entre com `demo@acertou.local` e a senha escolhida. O script é idempotente.

## Desenvolvimento local

Backend: crie um ambiente virtual, instale `backend/requirements.txt`, execute `alembic upgrade head` e `uvicorn app.main:app --reload` dentro de `backend/`. Sem `DATABASE_URL`, usa SQLite local para desenvolvimento. Defina `SECRET_KEY` em produção.

Frontend: em `frontend/`, execute `npm install` e `npm run dev`. Na implantação com Docker, frontend, API e WebSocket usam a mesma origem por meio do Nginx. Fora do Docker, configure `VITE_API_URL=http://localhost:8000` antes de iniciar o Vite, pois o servidor de desenvolvimento não executa o proxy do Nginx.

## Testes

```bash
cd ~/Acertou
(cd backend && pytest -q)
(cd frontend && npm run build)
(cd frontend && npx playwright install chromium && npm run test:e2e)
(cd backend && python tests/load_100.py http://127.0.0.1:8000)
```

Para Playwright, mantenha frontend e backend locais em execução. O teste cria um professor, um quiz, uma sessão e um aluno real em viewports desktop e móvel. O teste backend usa SQLite de teste separado. O script de carga abre 100 conexões WebSocket, confere a presença e verifica que todas recebem o mesmo prazo de questão, depois da prévia de 5 segundos. Ele passou neste ambiente local, com uma instância e SQLite; repita a medição com PostgreSQL no ambiente de implantação.

## Eventos em tempo real

Conecte-se a `WS /ws/sessions/{id}?role=teacher|participant` com os subprotocolos `["acertou", token]`. O token é JWT do professor ou credencial de participação e não vai na URL. Cada mensagem segue `{ "event": "...", "data": { ... } }`. Na conexão, `state` contém o estado autorizado completo. Após `participant_joined`, `participant_left`, `countdown_started`, `question_preview_started`, `question_started`, `answer_submitted`, `question_paused`, `question_resumed`, `question_finished` e `session_finished`, o cliente recarrega o estado pela API. A prévia usa `preview_ends_at`; a resposta usa `ends_at`. O servidor valida os dois momentos. Durante a prévia, a API omite as alternativas. Durante a resposta, omite o acerto e os pontos individuais, inclusive em consultas de reconexão.

## Relatórios e CSV

O professor acessa resumo da turma, matriz por aluno, detalhe de cada resposta e análise por questão. Os três CSVs usam UTF-8 com BOM e `;` como separador. Na matriz, `1` significa acerto, `0` erro e vazio ausência de resposta. Valores iniciados por caracteres de fórmula recebem um apóstrofo para evitar execução em planilhas. Os resultados usam snapshots feitos na criação da sessão.

## Implantação e limites

O frontend pode ser hospedado separadamente; o backend precisa de PostgreSQL, conexão WebSocket e processo sempre ativo para o temporizador e agendamentos. Em uma implantação separada, configure HTTPS/WSS, `SECRET_KEY`, `DATABASE_URL`, `CORS_ORIGINS` e `VITE_API_URL`. A coordenação de WebSockets e temporizador é por processo: execute **uma instância** do backend. Para múltiplas instâncias, adicione Redis Pub/Sub, um líder de agendamento e bloqueios distribuídos. A capacidade de 100 conexões foi medida apenas no ambiente local; ainda precisa ser validada no ambiente de destino. Rate limiting é local ao processo. Exclusão de sessão é definitiva e restrita ao professor proprietário.

Melhorias futuras: infraestrutura distribuída, exportação XLSX e testes de carga automatizados.
