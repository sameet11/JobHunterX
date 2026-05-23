# Docker Setup & Commands

## Quick Start

```powershell
# 1. Authenticate with Google Cloud (ADC — do once)
gcloud auth application-default login

# 2. Copy .env.example to .env and configure credentials
cp .env.example .env
# Edit .env with GOOGLE_CLOUD_PROJECT and platform credentials

# 3. Start all services
docker-compose up -d

# 4. Check status
docker-compose ps

# 5. View logs
docker-compose logs -f app

# 6. Stop services
docker-compose down
```

**Note:** Docker automatically uses your local ADC credentials from `~/.config/gcloud` — no service account file needed.

---

## Services

| Service | Container Name | Port | Purpose |
|---------|---|---|---|
| **app** | jobhunterx-app | (none) | Main JobHunterX application |
| **postgres** | jobhunterx-db | 5432 | PostgreSQL database |
| **pgadmin** | jobhunterx-pgadmin | 5050 | Database UI (http://localhost:5050) |

---

## Common Commands

### Start Services
```powershell
# Start all services in background
docker-compose up -d

# Start with live logs
docker-compose up

# Start only specific service
docker-compose up -d postgres
docker-compose up -d app
```

### View Logs
```powershell
# View app logs (live)
docker-compose logs -f app

# View app logs (last 100 lines)
docker-compose logs --tail=100 app

# View all logs
docker-compose logs -f

# View specific service
docker-compose logs -f postgres
docker-compose logs -f pgadmin
```

### Stop/Remove Services
```powershell
# Stop all services (data persists)
docker-compose down

# Stop and remove all data
docker-compose down -v

# Stop specific service
docker-compose stop app
docker-compose stop postgres

# Remove specific service
docker-compose rm app
```

### Rebuild Application
```powershell
# Rebuild app image after code changes
docker-compose build app

# Rebuild and restart
docker-compose up -d --build app

# Force rebuild (no cache)
docker-compose build --no-cache app
```

### Interactive Shell
```powershell
# Access app container shell
docker-compose exec app bash

# Access PostgreSQL shell
docker-compose exec postgres psql -U jobhunter -d jobhunterx

# Run a command in app container
docker-compose exec app python -c "import config; print(config)"
```

### Check Health
```powershell
# Check if services are healthy
docker-compose ps

# Watch service status
docker stats

# Check specific container
docker inspect jobhunterx-app
```

---

## Environment Configuration

### Via `.env` file
Create/edit `.env` with your credentials:

```env
# Required
GOOGLE_CLOUD_PROJECT=your-gcp-project
LINKEDIN_EMAIL=your-email@gmail.com
LINKEDIN_PASSWORD=your-password
NAUKRI_EMAIL=your-naukri-email
NAUKRI_PASSWORD=your-naukri-password

# Optional
GOOGLE_SHEET_ID=your-sheet-id
SERPAPI_KEY=your-serpapi-key
HUNTER_API_KEY=your-hunter-key
```

### Override Environment
```powershell
# Pass env vars via docker-compose
docker-compose run -e DAILY_LIMIT=5 app python main.py

# Set in docker-compose.yml directly
# (not recommended — use .env instead)
```

---

## Volume Mounts

| Host Path | Container Path | Purpose |
|---|---|---|
| `./data` | `/app/data` | SQLite/PostgreSQL data, profiles, tokens |
| `./logs` | `/app/logs` | Application logs |
| `./output` | `/app/output` | Tailored resumes |
| `./.env` | `/app/.env` | Configuration (read-only) |
| `./config/gcp-service-account.json` | `/app/config/gcp-service-account.json` | GCP credentials (read-only) |

---

## Database Access

### PostgreSQL Connection (from host)
```powershell
# Install psql locally (or use pgAdmin UI)
psql -h localhost -U jobhunter -d jobhunterx

# From container
docker-compose exec postgres psql -U jobhunter -d jobhunterx
```

### pgAdmin Web UI
- URL: http://localhost:5050
- Email: `admin@jobhunterx.local`
- Password: `admin_password`

**Add server in pgAdmin:**
1. Right-click Servers → Register → Server
2. Name: `jobhunterx`
3. Connection tab:
   - Host: `postgres` (Docker network)
   - Port: `5432`
   - User: `jobhunter`
   - Password: `jobhunter_dev_password`

---

## Troubleshooting

### Container exits immediately
```powershell
# Check logs
docker-compose logs app

# Common causes:
# - Missing .env file
# - Invalid credentials
# - Missing GCP credentials file
```

### Port already in use
```powershell
# Change port in docker-compose.yml
# E.g., PostgreSQL on 5433 instead of 5432:
# ports:
#   - "5433:5432"

# Or stop the service using the port
docker-compose down
```

### Database connection refused
```powershell
# Ensure PostgreSQL is healthy
docker-compose ps postgres

# Check PostgreSQL logs
docker-compose logs postgres

# Wait for PostgreSQL startup (takes ~10s)
# docker-compose waits by default, but may need time
```

### Playwright browser issues
```powershell
# Rebuild with latest Playwright
docker-compose build --no-cache app

# Verify browsers installed
docker-compose exec app playwright install --list
```

### Permission denied errors
```powershell
# App runs as non-root user (UID 1000)
# Ensure data/ and logs/ directories are writable:
chmod 755 data logs output
```

---

## Production Deployment

### Docker Swarm
```powershell
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml jobhunterx

# View stack
docker stack ls
docker stack ps jobhunterx

# Remove stack
docker stack rm jobhunterx
```

### Kubernetes (with Helm)
```bash
# Convert docker-compose to k8s manifests
kompose convert -f docker-compose.yml

# Deploy to k8s
kubectl apply -f jobhunterx-app-service.yaml
```

### Cloud Run / App Engine
```bash
# Build and push to Google Container Registry
gcloud builds submit --tag gcr.io/PROJECT_ID/jobhunterx

# Deploy
gcloud run deploy jobhunterx --image gcr.io/PROJECT_ID/jobhunterx
```

---

## Advanced Configuration

### Custom Python Version
Edit `Dockerfile`:
```dockerfile
FROM python:3.11-slim  # Change from 3.12
```

### Additional System Dependencies
Edit `Dockerfile` in the `apt-get install` section:
```dockerfile
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    libpq-dev \
    gcc \
    ffmpeg \  # Add new packages here
    && rm -rf /var/lib/apt/lists/*
```

### Multi-stage Build (smaller image)
```dockerfile
FROM python:3.12-slim as builder
# Build stage...

FROM python:3.12-slim as runtime
# Runtime stage...
```

---

## Performance Tips

### Reduce Build Time
```powershell
# Cache layers by keeping Dockerfile efficient
docker-compose build --no-cache  # Force rebuild
```

### Reduce Image Size
- Use `-slim` base image (not `full`)
- Remove build dependencies in Dockerfile
- Multi-stage builds

### Speed Up Database Startup
- Database initializes on first run (via `init_db.sql`)
- Set `POSTGRES_INITDB_ARGS` to customize

### Enable Compose Caching
```powershell
# Docker Compose will cache successfully built layers
docker-compose build app
docker-compose build app  # Much faster (uses cache)
```

---

## See Also
- [SETUP.md](./SETUP.md) — Full setup guide
- [docker-compose.yml](./docker-compose.yml) — Service configuration
- [Dockerfile](./Dockerfile) — App image definition
