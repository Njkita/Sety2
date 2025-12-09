FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] \
    psycopg2-binary grpcio grpcio-tools pydantic lxml

COPY app ./app

RUN python -m grpc_tools.protoc \
    -I ./app/proto \
    --python_out=. \
    --grpc_python_out=. \
    app/proto/notes.proto

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
