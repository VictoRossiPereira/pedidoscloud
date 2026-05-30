"""
PedidosCloud - Serviço de Pedidos
Responsável por criar, consultar e gerenciar pedidos.
"""
import os
import uuid
import logging
from datetime import datetime
from typing import Optional, List
from enum import Enum

import httpx
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Float, DateTime, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","service":"orders","msg":"%(message)s"}'
)
logger = logging.getLogger(__name__)

# ── Métricas ──────────────────────────────────────────────────────────────────
ORDERS_CREATED = Counter("orders_created_total", "Total de pedidos criados")
ORDER_ERRORS   = Counter("orders_errors_total", "Erros no serviço de pedidos", ["type"])

# ── Banco de dados ────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://pedidos:pedidos@postgres:5432/pedidoscloud"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class OrderDB(Base):
    __tablename__ = "orders"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id  = Column(String, nullable=False)
    product_id   = Column(String, nullable=False)
    quantity     = Column(Float, nullable=False)
    total_price  = Column(Float, nullable=False)
    status       = Column(String, default="PENDING")
    created_at   = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ── Schemas ───────────────────────────────────────────────────────────────────
class OrderStatus(str, Enum):
    PENDING    = "PENDING"
    CONFIRMED  = "CONFIRMED"
    CANCELLED  = "CANCELLED"
    DELIVERED  = "DELIVERED"

class CreateOrderRequest(BaseModel):
    customer_id : str = Field(..., example="cust-001")
    product_id  : str = Field(..., example="prod-123")
    quantity    : float = Field(..., gt=0, example=2)
    unit_price  : float = Field(..., gt=0, example=49.90)

class OrderResponse(BaseModel):
    id          : str
    customer_id : str
    product_id  : str
    quantity    : float
    total_price : float
    status      : str
    created_at  : datetime

# ── DI: DB Session ────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Serviços externos ─────────────────────────────────────────────────────────
INVENTORY_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8003")
PAYMENTS_URL  = os.getenv("PAYMENTS_SERVICE_URL",  "http://payments-service:8002")

app = FastAPI(title="PedidosCloud Orders Service", version="1.0.0")

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "orders"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(req: CreateOrderRequest, db: Session = Depends(get_db)):
    logger.info(f"Criando pedido para customer={req.customer_id} product={req.product_id}")

    # 1. Reservar estoque
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            inv_resp = await client.post(
                f"{INVENTORY_URL}/inventory/reserve",
                json={"product_id": req.product_id, "quantity": req.quantity}
            )
            if inv_resp.status_code != 200:
                ORDER_ERRORS.labels(type="inventory").inc()
                raise HTTPException(status_code=422, detail="Estoque insuficiente")
        except httpx.ConnectError:
            ORDER_ERRORS.labels(type="inventory_conn").inc()
            raise HTTPException(status_code=503, detail="Serviço de estoque indisponível")

    # 2. Persistir pedido
    order = OrderDB(
        customer_id=req.customer_id,
        product_id=req.product_id,
        quantity=req.quantity,
        total_price=req.quantity * req.unit_price,
        status=OrderStatus.PENDING
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    ORDERS_CREATED.inc()
    logger.info(f"Pedido criado id={order.id}")

    # 3. Iniciar pagamento (async — não bloqueia resposta)
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            await client.post(
                f"{PAYMENTS_URL}/payments/process",
                json={"order_id": order.id, "amount": order.total_price}
            )
        except Exception:
            logger.warning("Pagamento enfileirado para retry")

    return order

@app.get("/orders", response_model=List[OrderResponse])
def list_orders(customer_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(OrderDB)
    if customer_id:
        q = q.filter(OrderDB.customer_id == customer_id)
    return q.order_by(OrderDB.created_at.desc()).limit(100).all()

@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return order

@app.put("/orders/{order_id}/status", response_model=OrderResponse)
def update_status(order_id: str, status: OrderStatus, db: Session = Depends(get_db)):
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    order.status = status
    db.commit()
    db.refresh(order)
    logger.info(f"Pedido {order_id} atualizado para {status}")
    return order
