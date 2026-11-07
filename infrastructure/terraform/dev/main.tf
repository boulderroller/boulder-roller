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

  environment         = "dev"
  name_prefix         = "boulder-dev"
  region              = var.region
  vpc_cidr            = var.vpc_cidr
  ssh_key_ids         = var.ssh_key_ids
  api_count           = 1
  api_droplet_size    = "s-2vcpu-4gb"
  api_port            = 8080
  healthcheck_path    = "/health/db"
  domain              = var.domain
  enable_database     = var.enable_database
  enable_redis        = var.enable_redis
  create_load_balancer = true
}
