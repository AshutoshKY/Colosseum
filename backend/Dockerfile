FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv (without installing the project package itself first)
RUN uv sync --frozen --no-install-project --extra dev

# Copy application source code
COPY backend /app/backend
COPY data /app/data
COPY scripts /app/scripts
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY README.md /app/README.md

# Install the project package itself
RUN uv sync --frozen --extra dev

# Expose FastAPI port
EXPOSE 8100

# Start command: runs database migrations, seeds prompts, and starts the FastAPI server
CMD ["sh", "-c", "uv run alembic upgrade head && uv run python scripts/seed_prompts.py && uv run uvicorn app.api.main:app --app-dir backend --host 0.0.0.0 --port 8100"]
