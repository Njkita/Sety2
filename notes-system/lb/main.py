import asyncio
import ssl
import os

from fastapi import FastAPI, Request, Response
import httpx
import uvicorn

from backends import Backend, BackendPool

app = FastAPI()

# HTTP-бэкенды (REST+SOAP)
http_backends = BackendPool([
    Backend(name="svc1", url="http://service1:8000"),
    Backend(name="svc2", url="http://service2:8000"),
])

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(http_backends.health_check_loop())
    asyncio.create_task(start_grpc_lb())


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_all(full_path: str, request: Request):
    """
    Прокси для REST+SOAP: всё, что пришло, пробрасываем на выбранный backend.
    Таймаут 2 сек.
    """
    backend = http_backends.pick_backend()
    if not backend:
        return Response(status_code=503, content="No backend available")

    url = f"{backend.url}/{full_path}"
    method = request.method
    headers = dict(request.headers)
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.request(method, url, headers=headers, content=body)
    except Exception:
        backend.record_failure()
        return Response(status_code=502, content="Backend error")

    backend.record_success()
    return Response(
        status_code=r.status_code,
        content=r.content,
        headers={k: v for k, v in r.headers.items()
                 if k.lower() not in ["content-length", "transfer-encoding", "connection"]},
    )

# === gRPC TCP LB (L4) ===

GRPC_BACKENDS = [("service1", 50051), ("service2", 50051)]

async def handle_grpc_client(reader, writer):
    """
    Простой TCP proxy: выбираем backend, открываем соединение, прокидываем байты в обе стороны.
    """
    backend = GRPC_BACKENDS[handle_grpc_client.counter % len(GRPC_BACKENDS)]
    handle_grpc_client.counter += 1
    host, port = backend

    try:
        backend_reader, backend_writer = await asyncio.open_connection(host, port)
    except Exception:
        writer.close()
        await writer.wait_closed()
        return

    async def pipe(src, dst):
        try:
            while True:
                data = await src.read(1024 * 16)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except Exception:
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

    await asyncio.gather(
        pipe(reader, backend_writer),
        pipe(backend_reader, writer),
    )

handle_grpc_client.counter = 0

async def start_grpc_lb():
    """
    gRPC LB с TLS (наш балансировщик поддерживает https и для gRPC).
    Клиенты gRPC подключаются к этому порту.
    """
    certfile = os.path.join("certs", "lb.crt")
    keyfile = os.path.join("certs", "lb.key")
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(certfile, keyfile)
    ssl_ctx.set_alpn_protocols(["h2"])

    server = await asyncio.start_server(
        handle_grpc_client,
        host="0.0.0.0",
        port=8444,
        ssl=ssl_ctx,
    )
    print("[LB] gRPC LB listening on :8444 (TLS)")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain("certs/lb.crt", "certs/lb.key")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8443,
        ssl_keyfile="certs/lb.key",
        ssl_certfile="certs/lb.crt",
    )
