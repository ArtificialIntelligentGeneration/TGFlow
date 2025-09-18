SLAVA Licensing API (Stage 2)

Quick start (local)

1. Create and activate Python 3.10 venv
2. Install deps:
   ```bash
   pip install -r server/requirements.txt
   ```
3. Start Postgres and Redis (via Docker):
   ```bash
   docker compose -f server/docker-compose.yml up -d postgres redis
   ```
4. Run migrations:
   ```bash
   (cd server && alembic -c alembic.ini upgrade head)
   ```
5. Seed data:
   ```bash
   python server/scripts/seed.py
   ```
6. Generate JWT keys:
   ```bash
   mkdir -p server/keys
   openssl genrsa -out server/keys/jwtRS256.key 2048
   openssl rsa -in server/keys/jwtRS256.key -pubout -out server/keys/jwtRS256.key.pub
   ```
7. Run API:
   ```bash
   uvicorn server.app.main:app --reload --port 8000
   ```

Env
Copy `server/env.example` as a baseline and set environment variables in your shell or create `server/.env` (loaded automatically). When running locally without Docker, defaults point to localhost for DB/Redis.

Endpoints
- POST `/auth/login` { email, password, device_fingerprint? }
- GET `/license`
- POST `/usage/reserve`
- POST `/usage/commit`
- POST `/usage/rollback`
- GET `/plans`
- GET `/.well-known/jwks.json` (public key bundle for Desktop)

See `server/openapi/licensing.yml` for details.

Notes
- JWT RS256, keys loaded from `server/keys/` by default.
- Reservation TTL is 15 minutes.
- Rate limits enforced with Redis (graceful degrade if Redis down).
- Env loading: `.env` in project root is ignored; use shell env or `server/.env`.

p95 testing (outline)
- Use `pytest -q` for unit/integration.
- For load: run a short script or k6/vegeta to sustain 20 rps per endpoint for 5–10 min; parse Prometheus `/metrics` histograms `http_request_latency_seconds_bucket` to compute p95, or collect client-side latencies and aggregate.


