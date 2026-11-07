variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "name_prefix" {
  description = "Prefix applied to all resource names"
  type        = string
}

variable "region" {
  description = "DigitalOcean region slug (e.g., nyc3, sfo3)"
  type        = string
  default     = "nyc3"
}

variable "vpc_cidr" {
  description = "CIDR range for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "ssh_key_ids" {
  description = "List of SSH key IDs to inject into droplets"
  type        = list(string)
  default     = []
}

variable "api_image" {
  description = "Droplet image slug"
  type        = string
  default     = "docker-20-04"
}

variable "api_droplet_size" {
  description = "Droplet size slug"
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "api_count" {
  description = "Number of API droplets to provision"
  type        = number
  default     = 1
}

variable "api_port" {
  description = "Internal port the API container listens on"
  type        = number
  default     = 8080
}

variable "healthcheck_path" {
  description = "Healthcheck path for load balancer"
  type        = string
  default     = "/health/db"
}

variable "domain" {
  description = "Primary domain for the API (used for TLS)"
  type        = string
  default     = ""
}

variable "certificate_name" {
  description = "Existing certificate name to reuse (optional)"
  type        = string
  default     = ""
}

variable "create_load_balancer" {
  description = "Whether to create a load balancer in front of droplets"
  type        = bool
  default     = true
}

variable "enable_database" {
  description = "Provision a managed PostgreSQL cluster"
  type        = bool
  default     = true
}

variable "enable_redis" {
  description = "Provision a managed Redis cluster"
  type        = bool
  default     = true
}

variable "database_size" {
  description = "Managed database size"
  type        = string
  default     = "db-s-2vcpu-4gb"
}

variable "database_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "15"
}

variable "database_node_count" {
  description = "Number of database nodes (1 for dev, >1 for HA)"
  type        = number
  default     = 1
}

variable "redis_size" {
  description = "Managed Redis size"
  type        = string
  default     = "db-s-1vcpu-1gb"
}

variable "redis_version" {
  description = "Redis version"
  type        = string
  default     = "7"
}

variable "redis_node_count" {
  description = "Number of Redis nodes"
  type        = number
  default     = 1
}
