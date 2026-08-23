# ALI Home Installation

## Requirements

- Mini PC, Raspberry Pi 5, or server capable of running Docker.
- Docker and Docker Compose.
- Optional: Home Assistant already installed and reachable on the local network.
- Optional: OpenAI API key for advanced conversation.

## Install

```bash
git clone <your-repository-url> ali-home
cd ali-home
cp .env.example .env
```

Edit `.env` and set only the services you want to enable.

```bash
docker compose up --build -d
```

Check:

```bash
curl http://localhost:8000/api/health
```

Or run the full Phase 1 validation:

```bash
./scripts/validate.sh
```

## Backups

Back up:

- `.env`
- Docker volume `ali_data`
- repository code

Do not commit `.env` or database files.

## Restore

```bash
git clone <your-repository-url> ali-home
cd ali-home
cp /backup/.env .env
docker volume create ali-home_ali_data
# Restore your saved ali_data volume backup before starting containers.
docker compose up --build -d
```

The exact volume name may be prefixed by the directory name. Check it with:

```bash
docker volume ls | grep ali_data
```
