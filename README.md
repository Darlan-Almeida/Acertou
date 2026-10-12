# Acertou

**English** · [Português (Brasil)](README.pt-BR.md)

A live quiz platform for teachers and students. Teachers create quizzes and control sessions; students join with a code and name, without an account. Answers, session state, and reports are stored in the database.

Each question begins with **5 seconds showing only the prompt**. The answer choices then appear for the time configured by the teacher. The server stores both deadlines. After submitting an answer, a student sees only that it was recorded; correctness, points, and the correct choice are revealed when the question timer expires. At the end, the teacher sees the top three students on the session screen.

## Project layout

- `frontend/`: React, TypeScript, Vite, responsive CSS, WebSocket, and Playwright tests.
- `backend/app/`: FastAPI, SQLAlchemy models, authentication, timers, WebSocket, reports, and CSV export.
- `backend/migrations/`: Alembic migrations.
- `backend/tests/`: integration flow with three participants and five questions.
- `docker-compose.yml`: frontend, backend, PostgreSQL, and an optional temporary public tunnel.

## Run on your computer and share temporarily

Docker runs the frontend, API, and PostgreSQL on your computer. A [Cloudflare Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) provides a temporary public HTTPS address without opening router ports or creating a Cloudflare account. The address changes when the tunnel is recreated and works while your computer, Docker, and the tunnel are running. Quick Tunnels are intended for classes and testing, without an uptime guarantee. Cloudflare limits them to 200 simultaneous in-flight requests; WebSocket connections stay open during the class.

### 1. One-time setup

On Ubuntu 24.04 with `docker.io`, install Compose v2 and Buildx if they are not already available:

```bash
sudo apt update
sudo apt install docker-compose-v2 docker-buildx openssl
docker compose version
docker buildx version
```

Create your local configuration in the project directory. If `.env` already exists, keep it and verify that `SECRET_KEY` contains a long random value. **Keep the same `SECRET_KEY` between classes**, or existing login tokens will stop working.

```bash
cd ~/Acertou
cp -n .env.example .env
if grep -q '^SECRET_KEY=replace-with-a-long-random-secret$' .env; then
  sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
fi
```

This replaces only the example `SECRET_KEY`; an existing custom value is preserved. PostgreSQL data and quizzes persist in the `postgres_data` volume between runs.

### 2. Start a class

Run these commands from the project directory:

```bash
cd ~/Acertou
docker compose --profile public up --build -d
docker compose logs -f tunnel
```

Wait for a URL such as `https://some-name.trycloudflare.com` in the logs. Use this address for the teacher and students, including phones. The session QR code uses the same public address. Press `Ctrl+C` to stop viewing the logs; the containers keep running. Open the URL and sign in or create a teacher account. Check container status with:

```bash
docker compose --profile public ps
```

The site is also available only on your computer at `http://localhost:5173`; local API docs are at `http://localhost:8000/docs`. The backend runs `alembic upgrade head` on startup. Local ports bind to `127.0.0.1`, while the tunnel publishes the site, which forwards API and WebSocket traffic internally.

### 3. End the class

```bash
cd ~/Acertou
docker compose --profile public down
```

This closes the public address and stops the containers. It keeps the PostgreSQL volume; **do not use `down -v`** if you want to retain quizzes, accounts, and results. For the next class, repeat step 2 and share the new address. Anyone with the link can open the site and create a teacher account because registration is public. Use a strong password, share the link only with your class, and avoid real student IDs or other sensitive data until access controls are strengthened.

To add a sample five-question quiz:

```bash
docker compose exec -e DEMO_PASSWORD='choose-a-strong-password' backend python -m app.seed
```

Sign in as `demo@acertou.local` with the chosen password. The seed script can be run more than once.

## Local development

Backend: create a virtual environment, install `backend/requirements.txt`, run `alembic upgrade head`, and start `uvicorn app.main:app --reload` from `backend/`. Without `DATABASE_URL`, it uses a local SQLite database for development. Set `SECRET_KEY` for deployment.

Frontend: run `npm install` and `npm run dev` from `frontend/`. With Docker, the frontend, API, and WebSocket use the same origin through Nginx. Outside Docker, set `VITE_API_URL=http://localhost:8000` before starting Vite, because the Vite development server does not use the Nginx proxy.

## Tests

```bash
cd ~/Acertou
(cd backend && pytest -q)
(cd frontend && npm run build)
(cd frontend && npx playwright install chromium && npm run test:e2e)
(cd backend && python tests/load_100.py http://127.0.0.1:8000)
```

Keep the local frontend and backend running for Playwright. The browser test creates a teacher, quiz, session, and student in desktop and mobile viewports. Backend tests use a separate SQLite database. The load script opens 100 WebSocket connections, checks presence, and verifies that all receive the same question deadline after the 5-second prompt preview. This passed locally with one instance and SQLite; repeat the measurement with PostgreSQL in the target environment.

## Real-time events

Connect to `WS /ws/sessions/{id}?role=teacher|participant` using the subprotocols `["acertou", token]`. The token is a teacher JWT or participation credential and does not go in the URL. Each message has the shape `{ "event": "...", "data": { ... } }`. On connection, `state` contains the full authorized state. After `participant_joined`, `participant_left`, `countdown_started`, `question_preview_started`, `question_started`, `answer_submitted`, `question_paused`, `question_resumed`, `question_finished`, and `session_finished`, the client reloads state through the API. The preview uses `preview_ends_at`; answering uses `ends_at`. The server checks both deadlines. The API omits choices during preview and hides correctness and individual points during answering, including on reconnection.

## Reports and CSV

Teachers can view a class summary, student matrix, each answer, and analysis by question. The three CSV exports use UTF-8 with BOM and `;` as delimiter. In the matrix, `1` means correct, `0` means incorrect, and an empty cell means no answer. Values that could be interpreted as spreadsheet formulas are prefixed with an apostrophe. Results use snapshots captured when the session is created.

## Deployment limits

The frontend can be hosted separately; the backend needs PostgreSQL, WebSocket connectivity, and an always-running process for timers and scheduled sessions. For separate hosting, configure HTTPS/WSS, `SECRET_KEY`, `DATABASE_URL`, `CORS_ORIGINS`, and `VITE_API_URL`. WebSocket coordination and timers are per process: run **one backend instance**. Multiple instances require Redis Pub/Sub, a scheduling leader, and distributed locks. The 100-connection measurement was local only and still needs validation in the target environment. Rate limiting is local to the process. Session deletion is permanent and restricted to the owning teacher.

Potential future work: distributed infrastructure, XLSX export, and automated load tests.
