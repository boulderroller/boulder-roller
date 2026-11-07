terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

locals {
  tags      = [var.environment, "${var.name_prefix}-api"]
  cert_name = var.certificate_name != "" ? var.certificate_name : (var.domain != "" ? digitalocean_certificate.api[0].name : "")
}

resource "digitalocean_vpc" "main" {
  name     = "${var.name_prefix}-vpc"
  region   = var.region
  ip_range = var.vpc_cidr
}

resource "digitalocean_database_cluster" "postgres" {
  count      = var.enable_database ? 1 : 0
  name       = "${var.name_prefix}-db"
  engine     = "pg"
  version    = var.database_version
  size       = var.database_size
  region     = var.region
  node_count = var.database_node_count
  tags       = local.tags
  private_network_uuid = digitalocean_vpc.main.id
}

resource "digitalocean_database_cluster" "redis" {
  count      = var.enable_redis ? 1 : 0
  name       = "${var.name_prefix}-redis"
  engine     = "redis"
  version    = var.redis_version
  size       = var.redis_size
  region     = var.region
  node_count = var.redis_node_count
  tags       = local.tags
  private_network_uuid = digitalocean_vpc.main.id
}

resource "digitalocean_certificate" "api" {
  count   = var.domain != "" ? 1 : 0
  name    = "${var.name_prefix}-cert"
  type    = "lets_encrypt"
  domains = [var.domain]
}

resource "digitalocean_droplet" "api" {
  count    = var.api_count
  image    = var.api_image
  name     = "${var.name_prefix}-api-${count.index + 1}"
  region   = var.region
  size     = var.api_droplet_size
  ssh_keys = var.ssh_key_ids
  tags     = local.tags
  vpc_uuid = digitalocean_vpc.main.id
  ipv6     = true
  monitoring = true

  user_data = <<-EOF
    #!/bin/bash
    set -e
    apt-get update
    apt-get install -y docker.io docker-compose-plugin curl
    systemctl enable docker
    systemctl start docker

    # Create deploy directory placeholder
    mkdir -p /opt/boulder
    chown root:root /opt/boulder
  EOF
}

resource "digitalocean_loadbalancer" "api" {
  count = var.create_load_balancer ? 1 : 0

  name   = "${var.name_prefix}-lb"
  region = var.region
  vpc_uuid = digitalocean_vpc.main.id
  droplet_ids = [for d in digitalocean_droplet.api : d.id]

  forwarding_rule {
    entry_protocol  = "http"
    entry_port      = 80
    target_protocol = "http"
    target_port     = var.api_port
  }

  dynamic "forwarding_rule" {
    for_each = local.cert_name != "" ? [local.cert_name] : []
    content {
      entry_protocol   = "https"
      entry_port       = 443
      target_protocol  = "http"
      target_port      = var.api_port
      certificate_name = forwarding_rule.value
    }
  }

  healthcheck {
    protocol = "http"
    port     = var.api_port
    path     = var.healthcheck_path
  }

  sticky_sessions {
    type = "none"
  }

  depends_on = [digitalocean_certificate.api]
}
