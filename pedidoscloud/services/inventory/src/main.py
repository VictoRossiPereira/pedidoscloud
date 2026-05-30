"""
PedidosCloud - Serviço de Estoque
Gerencia reserva e baixa de itens do inventário.
"""
import os
import uuid
import logging
from datetime import datetime
from threading import Lock
from typing import List, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","service":"inventory","msg":"%(message)s"}'
)
logger = logging.getLogger(__name__)

RESERVES_TOTAL   = Counter("inventory_reserves_total",  "Reservas realizadas", ["status"])
STOCK_LEVEL      = Gauge("inventory_stock_level", "Nível de estoque por produto", ["product_id"])

# ── In-memory store com lock para thread-safety ───────────────────────────────
_lock = Lock()
_stock: Dict[str, float] = {
    "prod-001": 100.0,
    "prod-002": 50.0,
    "prod-003": 200.0,
    "prod-123": 75.0,
}
_reservations: Dict[str, dict] = {}

# Inicializar gauges
for pid, qty in _stock.items():
    STOCK_LEVEL.labels(product_id=pid).set(qty)

app = FastAPI(title="PedidosCloud Inventory Service", version="1.0.0")

# ── Schemas ───────────────────────────────────────────────────────────────────
class ReserveRequest(BaseModel):
    product_id : str = Field(..., example="prod-001")
    quantity   : float = Field(..., gt=0, example=5)
    order_id   : str | None = Field(default=None, example="ord-abc")

class ReleaseRequest(BaseModel):
    product_id : str
    quantity   : float
    order_id   : str | None = None

class StockItem(BaseModel):
    product_id       : str
    available        : float
    reserved         : float
    last_updated_at  : datetime

class ReservationResponse(BaseModel):
    reservation_id : str
    product_id     : str
    quantity       : float
    order_id       : str | None
    status         : str
    reserved_at    : datetime

# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_reserved_qty(product_id: str) -> float:
    return sum(
        r["quantity"] for r in _reservations.values()
        if r["product_id"] == product_id and r["status"] == "ACTIVE"
    )

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/inventory", response_model=List[StockItem])
def list_stock():
    with _lock:
        items = []
        for pid, qty in _stock.items():
            items.append(StockItem(
                product_id=pid,
                available=qty - _get_reserved_qty(pid),
                reserved=_get_reserved_qty(pid),
                last_updated_at=datetime.utcnow()
            ))
        return items

@app.get("/inventory/{product_id}", response_model=StockItem)
def get_stock(product_id: str):
    with _lock:
        if product_id not in _stock:
            raise HTTPException(status_code=404, detail="Produto não encontrado")
        reserved = _get_reserved_qty(product_id)
        return StockItem(
            product_id=product_id,
            available=_stock[product_id] - reserved,
            reserved=reserved,
            last_updated_at=datetime.utcnow()
        )

@app.post("/inventory/reserve", response_model=ReservationResponse)
def reserve_stock(req: ReserveRequest):
    with _lock:
        if req.product_id not in _stock:
            # Auto-criar produto desconhecido com estoque 0
            _stock[req.product_id] = 0.0
            STOCK_LEVEL.labels(product_id=req.product_id).set(0)

        available = _stock[req.product_id] - _get_reserved_qty(req.product_id)
        if available < req.quantity:
            RESERVES_TOTAL.labels(status="INSUFFICIENT").inc()
            logger.warning(f"Estoque insuficiente product={req.product_id} available={available} requested={req.quantity}")
            raise HTTPException(status_code=422, detail=f"Estoque insuficiente. Disponível: {available}")

        reservation_id = str(uuid.uuid4())
        _reservations[reservation_id] = {
            "reservation_id" : reservation_id,
            "product_id"     : req.product_id,
            "quantity"       : req.quantity,
            "order_id"       : req.order_id,
            "status"         : "ACTIVE",
            "reserved_at"    : datetime.utcnow(),
        }
        RESERVES_TOTAL.labels(status="OK").inc()
        logger.info(f"Reserva criada id={reservation_id} product={req.product_id} qty={req.quantity}")
        return _reservations[reservation_id]

@app.post("/inventory/release")
def release_stock(req: ReleaseRequest):
    """Libera reservas (ex.: pedido cancelado)."""
    with _lock:
        released = 0
        for rid, r in _reservations.items():
            if r["product_id"] == req.product_id and r["status"] == "ACTIVE":
                if req.order_id is None or r.get("order_id") == req.order_id:
                    r["status"] = "RELEASED"
                    released += r["quantity"]
        logger.info(f"Liberado {released} unidades de {req.product_id}")
        return {"released": released, "product_id": req.product_id}

@app.post("/inventory/confirm/{reservation_id}")
def confirm_reservation(reservation_id: str):
    """Confirma reserva, efetivando a baixa do estoque."""
    with _lock:
        r = _reservations.get(reservation_id)
        if not r:
            raise HTTPException(status_code=404, detail="Reserva não encontrada")
        if r["status"] != "ACTIVE":
            raise HTTPException(status_code=422, detail="Reserva não está ativa")
        pid = r["product_id"]
        _stock[pid] = max(0, _stock[pid] - r["quantity"])
        STOCK_LEVEL.labels(product_id=pid).set(_stock[pid])
        r["status"] = "CONFIRMED"
        logger.info(f"Reserva {reservation_id} confirmada. Novo estoque {pid}={_stock[pid]}")
        return {"message": "Estoque baixado com sucesso", "new_stock": _stock[pid]}

@app.post("/inventory/restock")
def restock(product_id: str, quantity: float):
    """Adiciona estoque a um produto."""
    with _lock:
        _stock[product_id] = _stock.get(product_id, 0) + quantity
        STOCK_LEVEL.labels(product_id=product_id).set(_stock[product_id])
        logger.info(f"Reabastecimento product={product_id} +{quantity} total={_stock[product_id]}")
        return {"product_id": product_id, "new_stock": _stock[product_id]}
