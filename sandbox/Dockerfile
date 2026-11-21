FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 WORKSPACE_DIR=/workspace

# Toolchains the assistant needs to build and test full-stack projects
RUN apt-get update \
 && apt-get install -y --no-install-recommends git nodejs npm build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY sandbox/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sandbox/runner.py .

EXPOSE 8080
# Runs as root only so it can drop each command to the unprivileged 'nobody' user.
CMD ["uvicorn", "runner:app", "--host", "0.0.0.0", "--port", "8080"]
