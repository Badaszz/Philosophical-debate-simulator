# ---------- Base Image ----------
FROM python:3.11-slim

# Prevent python buffering
ENV PYTHONUNBUFFERED=1

# ---------- Install uv ----------
RUN pip install uv

# ---------- Working directory ----------
WORKDIR /app

# ---------- Copy dependency files first (cache optimization) ----------
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen

# ---------- Copy project files ----------
COPY src .
COPY main.py .
COPY app.py .
COPY streamlit_app.py .
COPY .env .

# ---------- Expose ports ----------
EXPOSE 8000
EXPOSE 8501

# ---------- Start services ----------
CMD bash -c "\
uv run uvicorn app:app --host 0.0.0.0 --port 8000 & \
uv run streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0 \
"
