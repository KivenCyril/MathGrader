# Docker Deployment

This project is better deployed as three containers instead of one:

- `mysql`: stores users, submissions, and other Spring Boot data
- `python-agent`: runs the grading and OCR agent on port `5000`
- `java-backend`: serves the web UI and proxies agent requests on port `8080`

## Prerequisites

- Docker Desktop or Docker Engine with Compose support
- A local `settings.yaml` in the project root

The Python container mounts `./settings.yaml` into `/app/settings.yaml`, so your model keys stay outside the image.

## Start

```bash
docker compose up --build
```

After startup:

- Java backend: `http://localhost:8080`
- Python agent: `http://localhost:5000`
- MySQL: `localhost:3306`

## Run In Background

```bash
docker compose up --build -d
```

## Stop

```bash
docker compose down
```

To also remove the MySQL volume:

```bash
docker compose down -v
```

## Important Mounts

- `./settings.yaml -> /app/settings.yaml:ro`
- `./data -> /app/data`
- `./results -> /app/results`
- `./rubrics -> /app/rubrics:ro`

The Java backend also mounts `./data` and reads datasets from `/app/data/raw`.

## Environment Variables

These can be overridden from your shell or a Compose `.env` file:

- `MYSQL_DATABASE` default: `math_grader`
- `MYSQL_USER` default: `mathgrader`
- `MYSQL_PASSWORD` default: `mathgrader123`
- `MYSQL_ROOT_PASSWORD` default: `root123456`
- `MYSQL_PORT` default: `3306`
- `PYTHON_AGENT_PORT` default: `5000`
- `JAVA_BACKEND_PORT` default: `8080`
- `TZ` default: `Asia/Shanghai`

## Notes

- The Python image installs OCR-related dependencies from `requirements.txt`. This can make the image large and the first build slow.
- If you do not need local OCR tools such as `paddleocr` or `pix2tex`, you can slim the image later by splitting optional dependencies into a separate requirements file.
- The current Compose setup assumes `settings.yaml` already exists. If it does not, copy `settings.example.yaml` first and fill in your real keys.
