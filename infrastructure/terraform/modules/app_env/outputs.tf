output "vpc_id" {
  value = digitalocean_vpc.main.id
}

output "droplet_public_ips" {
  value = [for d in digitalocean_droplet.api : d.ipv4_address]
}

output "droplet_private_ips" {
  value = [for d in digitalocean_droplet.api : d.ipv4_address_private]
}

output "load_balancer_ip" {
  value = length(digitalocean_loadbalancer.api) > 0 ? digitalocean_loadbalancer.api[0].ip : null
}

output "database_uri" {
  value     = length(digitalocean_database_cluster.postgres) > 0 ? digitalocean_database_cluster.postgres[0].uri : null
  sensitive = true
}

output "redis_uri" {
  value     = length(digitalocean_database_cluster.redis) > 0 ? digitalocean_database_cluster.redis[0].uri : null
  sensitive = true
}
