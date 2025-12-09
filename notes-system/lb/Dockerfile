FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx

COPY main.py backends.py ./ 
COPY certs ./certs

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
