variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

variable "ssh_key_ids" {
  description = "SSH key IDs authorized to access droplets"
  type        = list(string)
  default     = []
}

variable "region" {
  description = "DigitalOcean region slug"
  type        = string
  default     = "nyc3"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "domain" {
  description = "Domain used for TLS (optional for dev)"
  type        = string
  default     = ""
}

variable "enable_database" {
  description = "Provision managed PostgreSQL for dev"
  type        = bool
  default     = true
}

variable "enable_redis" {
  description = "Provision managed Redis for dev"
  type        = bool
  default     = true
}
