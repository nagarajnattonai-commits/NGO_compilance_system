FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN groupadd --system setu && useradd --system --gid setu --home-dir /app setu \
    && mkdir -p /app/data && chown -R setu:setu /app
USER setu
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
