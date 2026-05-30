output "cluster_name" {
  description = "Nome do cluster GKE"
  value       = google_container_cluster.primary.name
}

output "cluster_endpoint" {
  description = "Endpoint do cluster GKE"
  value       = google_container_cluster.primary.endpoint
  sensitive   = true
}

output "postgres_connection_name" {
  description = "Connection name do Cloud SQL"
  value       = google_sql_database_instance.postgres.connection_name
}
