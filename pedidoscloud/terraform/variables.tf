variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "app_name" {
  description = "Nome da aplicação"
  type        = string
  default     = "pedidoscloud"
}

variable "environment" {
  description = "Ambiente (dev | staging | prod)"
  type        = string
  default     = "prod"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment deve ser dev, staging ou prod."
  }
}

variable "min_nodes" {
  description = "Mínimo de nós no cluster"
  type        = number
  default     = 2
}

variable "max_nodes" {
  description = "Máximo de nós no cluster"
  type        = number
  default     = 8
}

variable "machine_type" {
  description = "Tipo de máquina GKE"
  type        = string
  default     = "e2-standard-2"
}

variable "db_tier" {
  description = "Tier do Cloud SQL"
  type        = string
  default     = "db-g1-small"
}

variable "db_password" {
  description = "Senha do banco de dados"
  type        = string
  sensitive   = true
}
