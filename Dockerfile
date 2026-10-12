FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --only main --no-interaction

COPY src ./src

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
