# Sety2

# Сервис заметок: REST / gRPC / SOAP + балансировщики и шардирование

# 1. Структура проекта

```
notes-system/
│
├── docker-compose.yml
│
├── lb/
│   ├── main.py
│   ├── Dockerfile
│   ├── backends.py
│   └── certs/
│          # lb.crt и lb.key
│
├── nginx/
│   ├── nginx.conf
│   └── certs/
│          # nginx.crt и nginx.key
│
├── service/
│   ├── Dockerfile
│   └── app/
│       ├── main.py
│       ├── __init__.py
│       ├── storage.py
│       └── proto/
│           └── notes.proto
│
├── grpc_client.py
├── notes_pb2_grpc.py # генерируется protoc
└── notes_pb2.py # генерируется protoc
```

---

# 2. Сборка и запуск

## 2.1. Сборка Docker-образов

```
docker compose build
```

- Собирается образ **service**:
  - ставится Python + FastAPI
  - копируется приложение
  - генерируется gRPC код по `notes.proto`

- Собирается образ **lb**
- Подтягивается официальный образ **Nginx**
- Подтягиваются и запускаются два Postgres-шарда из официального Docker-образа

---

## 2.2. Запуск

```
docker compose up
```

Должно появиться:

### В сервисах:
```
Uvicorn running on http://0.0.0.0:8000
[gRPC] listening on :50051
```

### В балансировщике:
```
[LB] gRPC LB listening on :8444 (TLS)
Uvicorn running on https://0.0.0.0:8443
```

### В nginx:
```
Configuration complete; ready for start up
```

---

# 3. Проверка работы

В новом терминале:

## 3.1. Health-check

```
curl -k https://localhost/health
```

Ожидаемый ответ:

```
{"status":"ok"}
```

---

# 4. REST API

Все запросы идут через HTTPS на Nginx:

```
https://localhost/notes
```

## 4.1. Создать заметку

```
curl -k -X POST https://localhost/notes   -H "Content-Type: application/json"   -d '{"title": "test", "description": "from curl"}'
```

## 4.2. Список заметок

```
curl -k https://localhost/notes
```

## 4.3. Получить по id

```
curl -k https://localhost/notes/<id>
```

## 4.4. Обновить описание

```
curl -k -X PATCH https://localhost/notes/<id>   -H "Content-Type: application/json"   -d '{"description": "updated"}'
```

## 4.5. Удалить

```
curl -k -X DELETE https://localhost/notes/<id>
```

---

# 5. SOAP API

SOAP также идёт через Nginx:

```
POST https://localhost/soap
Content-Type: text/xml
```

## 5.1. ListNotes

```
curl -k https://localhost/soap   -H "Content-Type: text/xml"   -d '<?xml version="1.0"?>
<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
  <Body><ListNotes/></Body>
</Envelope>'
```

## 5.2. GetNote

Если заметка существует — вернётся SOAP-ответ с полями Note.

```
curl -k https://localhost/soap \
  -H "Content-Type: text/xml" \
  -d '<?xml version="1.0"?>
<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
  <Body>
    <GetNote>
      <Id>YOUR_ID_HERE</Id>
    </GetNote>
  </Body>
</Envelope>'
```

## 5.3. UpdateNoteDescription

Если заметки нет - SOAP Fault Note not found.

```
curl -k https://localhost/soap \
  -H "Content-Type: text/xml" \
  -d '<?xml version="1.0"?>
<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
  <Body>
    <UpdateNoteDescription>
      <Id>YOUR_ID_HERE</Id>
      <Description>updated via SOAP</Description>
    </UpdateNoteDescription>
  </Body>
</Envelope>'
```

## 5.4. DeleteNote

Если заметки нет - также Fault Note not found.

```
curl -k https://localhost/soap \
  -H "Content-Type: text/xml" \
  -d '<?xml version="1.0"?>
<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">
  <Body>
    <DeleteNote>
      <Id>YOUR_ID_HERE</Id>
    </DeleteNote>
  </Body>
</Envelope>'
```

Все примеры выполнены в диалоге — и рабочие.

---

# 6. gRPC API

Работает через Python-балансировщик (порт 8444, TLS).

## 6.1. Установка зависимостей для клиента

```
python3 -m pip install --user --break-system-packages grpcio grpcio-tools
```

## 6.2. Генерация gRPC-клиентских файлов

```
cp service/app/proto/notes.proto notes.proto

python3 -m grpc_tools.protoc   -I .   --python_out=.   --grpc_python_out=.   notes.proto
```

## 6.3. Запуск клиента

```
python3 grpc_client.py
```

Вывод:

```
gRPC Health: OK
gRPC ListNotes, count = 0
```

---

# 7. Шардирование

Реализовано в `service/app/storage.py`:

- Используются два Postgres-инстанса
- Для каждого id вычисляется SHA1
- По первому байту выбирается шард
- `list_notes` объединяет данные с обоих шардов

---

# 8. Собственный балансировщик (lb)

## Возможности:

- Поддерживает **HTTPS**
- Поддерживает **REST, SOAP**
- Поддерживает **gRPC (TLS + ALPN h2)**
- Реализует **circuit breaker**
- Делает health-check каждого backend’а
- Исключает упавшие backend’ы
- Возвращает backend в rotation при восстановлении
- Таймауты ≤ 2 сек на любой запрос

---

# 9. Проверка отказоустойчивости

## 9.1. Падает один backend (service1)

```
docker compose stop service1
curl -k https://localhost/notes
python3 grpc_client.py
```

Всё продолжает работать через service2.

---

## 9.2. Когда останавливаем оба:

```
docker compose stop service2
curl -k https://localhost/notes
python3 grpc_client.py
```

Результат:

- REST → 503 "No backend available"
- gRPC → DEADLINE_EXCEEDED

---

## 9.3. Поднимаем обратно

```
docker compose start service1 service2
curl -k https://localhost/health
curl -k https://localhost/notes
python3 grpc_client.py
```

Всё снова работает.
