"""
PedidosCloud - Serviço de Pagamentos
Simula integração com gateway de pagamento externo (ex: Stripe, PagSeguro).
"""
import os
import uuid
import random
import logging
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","service":"payments","msg":"%(message)s"}'
)
logger = logging.getLogger(__name__)

PAYMENTS_PROCESSED = Counter("payments_processed_total", "Pagamentos processados", ["status"])
PAYMENT_AMOUNT     = Histogram("payment_amount_brl", "Valor dos pagamentos em BRL",
                               buckets=[10, 50, 100, 250, 500, 1000, 5000])

# In-memory store (em produção: usar banco de dados)
_payments: dict = {}

app = FastAPI(title="PedidosCloud Payments Service", version="1.0.0")

# ── Schemas ───────────────────────────────────────────────────────────────────
class PaymentRequest(BaseModel):
    order_id : str = Field(..., example="ord-abc-123")
    amount   : float = Field(..., gt=0, example=99.80)
    method   : str = Field(default="credit_card", example="credit_card")

class PaymentResponse(BaseModel):
    id           : str
    order_id     : str
    amount       : float
    status       : str
    gateway_ref  : str
    processed_at : datetime

class ReserveRequest(BaseModel):
    order_id : str
    amount   : float

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "payments"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/payments/process", response_model=PaymentResponse, status_code=201)
def process_payment(req: PaymentRequest):
    logger.info(f"Processando pagamento order={req.order_id} amount={req.amount}")

    # Simula chamada ao gateway externo (90% aprovação)
    approved = random.random() < 0.90
    status   = "APPROVED" if approved else "DECLINED"

    payment = {
        "id"           : str(uuid.uuid4()),
        "order_id"     : req.order_id,
        "amount"       : req.amount,
        "status"       : status,
        "gateway_ref"  : f"GW-{uuid.uuid4().hex[:8].upper()}",
        "processed_at" : datetime.utcnow(),
    }
    _payments[payment["id"]] = payment

    PAYMENTS_PROCESSED.labels(status=status).inc()
    PAYMENT_AMOUNT.observe(req.amount)
    logger.info(f"Pagamento {payment['id']} status={status}")

    return payment

@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str):
    p = _payments.get(payment_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    return p

@app.get("/payments", response_model=List[PaymentResponse])
def list_payments(order_id: str | None = None):
    result = list(_payments.values())
    if order_id:
        result = [p for p in result if p["order_id"] == order_id]
    return sorted(result, key=lambda x: x["processed_at"], reverse=True)

@app.post("/payments/refund/{payment_id}", response_model=PaymentResponse)
def refund_payment(payment_id: str):
    p = _payments.get(payment_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    if p["status"] != "APPROVED":
        raise HTTPException(status_code=422, detail="Apenas pagamentos aprovados podem ser estornados")
    p["status"] = "REFUNDED"
    logger.info(f"Estorno realizado payment={payment_id}")
    return p
