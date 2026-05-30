# ════════════════════════════════════════════════════════════════════════════════
# PedidosCloud – Terraform IaC Skeleton
# Provisiona cluster GKE (Google Kubernetes Engine) + banco de dados Cloud SQL
# ════════════════════════════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }

  # Remote state – evita conflitos em time
  backend "gcs" {
    bucket = "pedidoscloud-tfstate"
    prefix = "prod/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ── VPC ──────────────────────────────────────────────────────────────────────
resource "google_compute_network" "vpc" {
  name                    = "${var.app_name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "${var.app_name}-subnet"
  ip_cidr_range = "10.0.0.0/16"
  region        = var.region
  network       = google_compute_network.vpc.id

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.1.0.0/16"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.2.0.0/20"
  }
}

# ── GKE Cluster ──────────────────────────────────────────────────────────────
resource "google_container_cluster" "primary" {
  name     = "${var.app_name}-cluster"
  location = var.region

  network    = google_compute_network.vpc.name
  subnetwork = google_compute_subnetwork.subnet.name

  # Remover node pool default (usaremos node pool dedicado)
  remove_default_node_pool = true
  initial_node_count       = 1

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Habilitar Workload Identity
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "primary_nodes" {
  name       = "${var.app_name}-node-pool"
  location   = var.region
  cluster    = google_container_cluster.primary.name

  autoscaling {
    min_node_count = var.min_nodes
    max_node_count = var.max_nodes
  }

  node_config {
    machine_type = var.machine_type
    disk_size_gb = 50

    # Apenas imagens otimizadas para containers
    image_type = "COS_CONTAINERD"

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]

    labels = {
      app = var.app_name
      env = var.environment
    }
  }
}

# ── Cloud SQL (PostgreSQL) ────────────────────────────────────────────────────
resource "google_sql_database_instance" "postgres" {
  name             = "${var.app_name}-pg-${var.environment}"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = var.environment == "prod" ? "REGIONAL" : "ZONAL"

    backup_configuration {
      enabled            = true
      start_time         = "03:00"
      binary_log_enabled = false
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }
  }

  deletion_protection = var.environment == "prod"
}

resource "google_sql_database" "db" {
  name     = "pedidoscloud"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "user" {
  name     = "pedidos"
  instance = google_sql_database_instance.postgres.name
  password = var.db_password  # Em produção: use Secret Manager
}
