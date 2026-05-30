# 🚀 PedidosCloud

> Plataforma de pedidos em microsserviços com Docker Compose, Kubernetes, CI/CD e Observabilidade.
> Projeto acadêmico – Cloud DevOps (UniFECAF 2026)

---

## 📐 Arquitetura

```
                         ┌─────────────────────────────────────────┐
                         │              Kubernetes Cluster          │
                         │                                          │
  Internet ──► LB ──►   │  ┌────────────┐                         │
                         │  │ API Gateway│ :8000                   │
                         │  └─────┬──────┘                         │
                         │        │ ClusterIP                       │
                         │   ┌────┴────────────────┐               │
                         │   │                     │               │
                         │ ┌─▼──────────┐  ┌───────▼────────┐     │
                         │ │  Orders    │  │   Inventory    │     │
                         │ │ Service    │  │   Service      │     │
                         │ │   :8001    │  │    :8003       │     │
                         │ └─────┬──────┘  └───────┬────────┘     │
                         │       │                  │              │
                         │ ┌─────▼──────┐  ┌───────▼────────┐    │
                         │ │  Payments  │  │   PostgreSQL   │    │
                         │ │  Service   │  │   (StatefulSet)│    │
                         │ │   :8002    │  │                │    │
                         │ └────────────┘  └────────────────┘    │
                         │                                         │
                         │  📊 Prometheus :9090  📈 Grafana :3000  │
                         └─────────────────────────────────────────┘
```

### Serviços

| Serviço         | Porta | Responsabilidade                          |
|-----------------|-------|-------------------------------------------|
| **api-gateway** | 8000  | Roteamento HTTP, rate limit, métricas     |
| **orders**      | 8001  | CRUD de pedidos, orquestra estoque+pgto   |
| **payments**    | 8002  | Integração com gateway externo (simulada) |
| **inventory**   | 8003  | Reserva e baixa de estoque                |
| PostgreSQL      | 5432  | Persistência dos pedidos                  |
| Prometheus      | 9090  | Coleta de métricas                        |
| Grafana         | 3000  | Dashboards                                |

---

## ⚡ Início Rápido (Local)

### Pré-requisitos

- Docker ≥ 24 e Docker Compose v2
- (Opcional) kubectl + cluster Kubernetes para produção

### Subir tudo localmente

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/pedidoscloud.git
cd pedidoscloud

# Build e start de todos os serviços
docker compose up --build

# Em background:
docker compose up --build -d
```

Aguarde ~30 segundos. Depois acesse:

| URL                                      | Descrição              |
|------------------------------------------|------------------------|
| http://localhost:8000/docs               | Swagger API Gateway    |
| http://localhost:8000/health             | Health check gateway   |
| http://localhost:8000/ready              | Readiness (verifica downstream) |
| http://localhost:8001/docs               | Swagger Orders         |
| http://localhost:8002/docs               | Swagger Payments       |
| http://localhost:8003/docs               | Swagger Inventory      |
| http://localhost:9090                    | Prometheus             |
| http://localhost:3000  (admin/admin)     | Grafana                |

### Testar fluxo completo

```bash
# 1. Verificar estoque disponível
curl http://localhost:8000/inventory/prod-001

# 2. Criar um pedido
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "cust-001",
    "product_id": "prod-001",
    "quantity": 2,
    "unit_price": 49.90
  }'

# 3. Consultar pedidos do cliente
curl "http://localhost:8000/orders?customer_id=cust-001"

# 4. Verificar estoque após reserva
curl http://localhost:8000/inventory/prod-001
```

### Parar o ambiente

```bash
docker compose down          # Para e remove containers
docker compose down -v       # Para, remove containers E volumes
```

---

## ☸️ Deploy em Kubernetes

```bash
# Aplicar todos os manifests
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/configmap.yaml
kubectl apply -f k8s/base/secret.yaml      # Edite antes com seus dados reais!
kubectl apply -f k8s/base/deployments.yaml
kubectl apply -f k8s/base/services.yaml
kubectl apply -f k8s/base/hpa.yaml

# Verificar status
kubectl get pods -n pedidoscloud
kubectl get svc  -n pedidoscloud
kubectl get hpa  -n pedidoscloud
```

---

## 🏗️ Infraestrutura com Terraform (GCP/GKE)

```bash
cd terraform

# Inicializar
terraform init

# Planejar
terraform plan -var="project_id=meu-projeto" -var="db_password=SenhaForte123"

# Aplicar
terraform apply -var="project_id=meu-projeto" -var="db_password=SenhaForte123"
```

---

## 📊 Observabilidade

### Métricas disponíveis (Prometheus)

| Métrica                              | Serviço       | Descrição                   |
|--------------------------------------|---------------|-----------------------------|
| `api_gateway_requests_total`         | api-gateway   | Total de requests por status |
| `api_gateway_request_duration_seconds` | api-gateway | Latência das requests        |
| `orders_created_total`               | orders        | Pedidos criados              |
| `orders_errors_total`                | orders        | Erros por tipo               |
| `payments_processed_total`           | payments      | Pagamentos por status        |
| `payment_amount_brl`                 | payments      | Histograma de valores        |
| `inventory_reserves_total`           | inventory     | Reservas por status          |
| `inventory_stock_level`              | inventory     | Nível de estoque por produto |

### Estratégia de Deploy: Rolling Update

Adotamos **Rolling Update** com `maxUnavailable: 0` e `maxSurge: 1` — garantindo zero downtime durante deploys. Em picos de tráfego, o HPA escala automaticamente as réplicas.

---

## 🗂️ Estrutura do Projeto

```
pedidoscloud/
├── services/
│   ├── api-gateway/        # FastAPI – Roteamento central
│   │   ├── src/main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── orders/             # FastAPI + SQLAlchemy + PostgreSQL
│   ├── payments/           # FastAPI – Integração gateway
│   └── inventory/          # FastAPI – Controle de estoque
├── k8s/
│   └── base/
│       ├── namespace.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       ├── deployments.yaml
│       ├── services.yaml
│       └── hpa.yaml
├── terraform/
│   ├── main.tf             # GKE + Cloud SQL
│   ├── variables.tf
│   └── outputs.tf
├── observability/
│   ├── prometheus.yml
│   └── grafana/
│       └── provisioning/
├── ci/
│   └── .github-actions-ci.yml   # Renomear para .github/workflows/ci.yml
├── docker-compose.yml
└── README.md
```

---

## 🎥 Vídeo Pitch

> 📌 Link do vídeo: **[Inserir link do YouTube após gravação]**

---

## 📚 Referências

- [Kubernetes Docs](https://kubernetes.io/docs/)
- [Docker Compose Reference](https://docs.docker.com/compose/)
- [The 12-Factor App](https://12factor.net/)
- [Terraform GCP Provider](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [OpenTelemetry](https://opentelemetry.io/)
- [Prometheus Python Client](https://github.com/prometheus/client_python)
