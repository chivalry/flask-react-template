# Flask React Template

A minimal full-stack template: **Flask** (Python) backend +
**React 18** (TypeScript + Vite) frontend.

## Stack

| Layer    | Technology                                    |
| -------- | --------------------------------------------- |
| Backend  | Flask, SQLAlchemy, Flask-Migrate, Flask-CORS  |
| Database | PostgreSQL 16                                 |
| Frontend | React 18, TypeScript, Vite, MUI, Axios        |
| Tooling  | Ruff, Pytest, ESLint, Prettier, Husky, Vitest |

## Quick start (local, no Docker)

```bash
# 1. Clone and enter the repo
git clone <your-repo-url>
cd flask-react-template

# 2. Copy and edit environment file
cp .env.example .env

# 3. Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app src_back.app db upgrade
flask --app src_back.app run

# 4. Frontend (new terminal)
npm install
npm run dev
```

Open <http://localhost:5173>.

## Docker

```bash
docker-compose up --build
```

Open <http://localhost:5173>.

## Project layout

```text
project/
├── src_back/          # Flask application
│   ├── app.py         # Application factory
│   ├── models.py      # SQLAlchemy models (BaseMixin)
│   ├── utils.py       # Shared helpers
│   ├── api/           # Blueprint routes
│   ├── seed.py        # Database seed stub
│   └── tests/         # Pytest suite
├── src_front/         # React application
│   ├── index.html
│   └── src/
│       ├── main.tsx   # Entry point
│       ├── App.tsx    # Root component + router
│       ├── api/       # Axios client
│       ├── components/
│       └── pages/
├── migrations/        # Alembic migrations
├── docker/            # Dockerfiles + entrypoint
├── .github/workflows/ # CI
└── docker-compose.yml
```

## Scripts

| Command                  | Description            |
| ------------------------ | ---------------------- |
| `npm run dev`            | Start Vite dev server  |
| `npm run build`          | Production build       |
| `npm run lint`           | ESLint                 |
| `npm run format`         | Prettier               |
| `npm test`               | Vitest (run once)      |
| `flask ... run`          | Start Flask dev server |
| `pytest`                 | Python tests           |
| `ruff check src_back/`   | Python linter          |
