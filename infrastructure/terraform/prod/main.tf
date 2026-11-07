terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

module "environment" {
  source = "../modules/app_env"

  environment          = "prod"
  name_prefix          = "boulder-prod"
  region               = var.region
  vpc_cidr             = var.vpc_cidr
  ssh_key_ids          = var.ssh_key_ids
  api_count            = 3
  api_droplet_size     = "c-4"
  api_port             = 8080
  healthcheck_path     = "/health/db"
  domain               = var.domain
  enable_database      = var.enable_database
  enable_redis         = var.enable_redis
  database_size        = "db-s-4vcpu-8gb"
  database_node_count  = 2
  redis_size           = "db-s-2vcpu-4gb"
  redis_node_count     = 2
  create_load_balancer = true
}
