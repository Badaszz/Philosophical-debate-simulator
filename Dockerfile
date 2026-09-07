# ---------- Backend image: FastAPI + the philo_agent LangGraph pipeline ----------
FROM python:3.13-slim

# Prevent python buffering
ENV PYTHONUNBUFFERED=1

# ---------- Install uv ----------
RUN pip install uv

# ---------- Working directory ----------
WORKDIR /app

# ---------- Copy dependency files first (cache optimization) ----------
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./

# Install dependencies using uv
RUN uv sync --frozen --no-dev

# ---------- Copy project files ----------
COPY backend/ .

# ---------- Expose port ----------
EXPOSE 8000

# ---------- Start the API ----------
# API keys are injected at runtime (e.g. via docker-compose `env_file`).
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]