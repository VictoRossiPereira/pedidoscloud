"""
PedidosCloud - API Gateway
Responsável por rotear requisições para os microsserviços internos.
"""
import os
import time
import logging
import httpx
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

# ── Logging estruturado ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","service":"api-gateway","msg":"%(message)s"}'
)
logger = logging.getLogger(__name__)

# ── Métricas Prometheus ──────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "api_gateway_requests_total",
    "Total de requisições recebidas",
    ["method", "endpoint", "status_code"]
)
REQUEST_LATENCY = Histogram(
    "api_gateway_request_duration_seconds",
    "Latência das requisições",
    ["method", "endpoint"]
)

# ── Configuração dos serviços downstream ─────────────────────────────────────
ORDERS_URL    = os.getenv("ORDERS_SERVICE_URL",    "http://orders-service:8001")
PAYMENTS_URL  = os.getenv("PAYMENTS_SERVICE_URL",  "http://payments-service:8002")
INVENTORY_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8003")

app = FastAPI(
    title="PedidosCloud API Gateway",
    version="1.0.0",
    description="Gateway central da plataforma PedidosCloud"
)

# ── Middleware de telemetria ──────────────────────────────────────────────────
@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code
    ).inc()
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    logger.info(f"method={request.method} path={request.url.path} status={response.status_code} duration={duration:.3f}s")
    return response

# ── Health / Readiness ────────────────────────────────────────────────────────
@app.get("/health", tags=["infra"])
async def health():
    return {"status": "ok", "service": "api-gateway"}

@app.get("/ready", tags=["infra"])
async def ready():
    """Verifica conectividade com serviços downstream."""
    checks = {}
    async with httpx.AsyncClient(timeout=2) as client:
        for name, url in [("orders", ORDERS_URL), ("payments", PAYMENTS_URL), ("inventory", INVENTORY_URL)]:
            try:
                r = await client.get(f"{url}/health")
                checks[name] = "ok" if r.status_code == 200 else "degraded"
            except Exception:
                checks[name] = "unreachable"
    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    code = 200 if overall == "ok" else 503
    return JSONResponse({"status": overall, "checks": checks}, status_code=code)

@app.get("/metrics", tags=["infra"])
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ── Proxy para Orders ─────────────────────────────────────────────────────────
@app.api_route("/orders/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], tags=["orders"])
async def proxy_orders(path: str, request: Request):
    return await _proxy(request, f"{ORDERS_URL}/orders/{path}")

@app.api_route("/orders", methods=["GET", "POST"], tags=["orders"])
async def proxy_orders_root(request: Request):
    return await _proxy(request, f"{ORDERS_URL}/orders")

# ── Proxy para Payments ───────────────────────────────────────────────────────
@app.api_route("/payments/{path:path}", methods=["GET", "POST", "PUT"], tags=["payments"])
async def proxy_payments(path: str, request: Request):
    return await _proxy(request, f"{PAYMENTS_URL}/payments/{path}")

# ── Proxy para Inventory ──────────────────────────────────────────────────────
@app.api_route("/inventory/{path:path}", methods=["GET", "POST", "PUT"], tags=["inventory"])
async def proxy_inventory(path: str, request: Request):
    return await _proxy(request, f"{INVENTORY_URL}/inventory/{path}")

@app.api_route("/inventory", methods=["GET", "POST"], tags=["inventory"])
async def proxy_inventory_root(request: Request):
    return await _proxy(request, f"{INVENTORY_URL}/inventory")

# ── Helper de proxy ───────────────────────────────────────────────────────────
async def _proxy(request: Request, target_url: str):
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
        except httpx.ConnectError:
            logger.error(f"Serviço indisponível: {target_url}")
            raise HTTPException(status_code=503, detail="Serviço temporariamente indisponível")
        except Exception as e:
            logger.error(f"Erro no proxy: {e}")
            raise HTTPException(status_code=502, detail="Erro de gateway")
