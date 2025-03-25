# Centralized Logging Service

A production-ready FastAPI-based microservice for centralized logging. It captures events and logs triggered by other services (like a Control Plane), processes them into a consistent format, and sends them to Google Cloud Logging. It also exposes endpoints to query and retrieve logs.

---

## Features

- RESTful API to submit and fetch logs
- Maps log types to GCP severity levels
- Asynchronous and scalable design with FastAPI
- Google Cloud Logging integration using official SDKs
- Factory pattern for consistent log entry creation
- Dockerized with Compose and Harness deployment support
- Full test suite with unit, integration, and load tests

---

## Tech Stack

- **Language:** Python 3.10
- **Framework:** FastAPI
- **Logging:** Google Cloud Logging (via SDK)
- **Tests:** Pytest, Locust (for load testing)
- **Packaging:** requirements.txt & pyproject.toml
- **Deployment:** Docker, Docker Compose, Harness

---

## Folder Structure

```
logging_service/
├── extensions/         # GCP logging logic
├── factory/            # Log factory (model construction)
├── models/             # Log schemas and enums
├── routes/             # FastAPI route handlers
├── tests/              # Pytest test suite
├── config.py           # Configuration from env
├── app.py              # FastAPI app entrypoint
├── Dockerfile          # Docker build instructions
├── docker-compose.yml  # Local dev orchestration
├── requirements.txt    # Package dependencies
├── pyproject.toml      # Optional dependency manager
└── README.md           # Project documentation
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Docker & Docker Compose
- (Optional) GCP credentials if running in a local dev setup

### Local Development

```bash
git clone <repo-url>
cd logging_service
docker-compose up --build
```

Then open:
```
http://localhost:8080/
```

---

## API Reference

### Health Check
`GET /`
```json
{ "message": "Logging Service is running!" }
```

### Submit Log
`POST /api/log`
```json
{
  "log_type": "INFO",
  "service_name": "control-plane",
  "data": {
    "message": "User created VM"
  }
}
```

### Fetch Logs
`GET /api/logs`

Returns logs from Google Cloud Logging.

---

## Environment Variables

| Variable               | Default               | Description                         |
|------------------------|-----------------------|-------------------------------------|
| `LOGGING_SERVICE_NAME` | centralized-logs      | GCP log stream name                 |
| `GCP_PROJECT_ID`       | test-project          | GCP project to write logs into      |

Use `.env` file or Harness secrets for managing these securely.

---

## Deployment

### Docker

```bash
docker build -t centralized-logger .
docker run -p 8080:8080 centralized-logger
```

### Docker Compose

```bash
docker-compose up --build
```

### Harness (Recommended for CI/CD)

- Use Dockerfile and `8080` as exposed port
- Set environment variables in pipeline YAML or secrets manager
- Add health check on `/`

---

## Testing

Run all tests:

```bash
pytest tests/
```

### Load Testing (Locust)

```bash
locust -f locustfile.py
```

Or simulate load manually using threads (see `test_main.py`)

---

## Contributing

- Follow PEP8 formatting (use `ruff` or `flake8`)
- Use feature branches
- Write/extend unit and integration tests for PRs

---

## Author

- **Rahul (Royalrahul23)** - [Project Maintainer]

---

## License

This project is for internal use. Licensing terms may apply based on deployment environments.