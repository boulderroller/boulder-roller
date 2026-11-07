output "droplet_public_ips" {
  value = module.environment.droplet_public_ips
}

output "droplet_private_ips" {
  value = module.environment.droplet_private_ips
}

output "load_balancer_ip" {
  value = module.environment.load_balancer_ip
}

output "database_uri" {
  value     = module.environment.database_uri
  sensitive = true
}

output "redis_uri" {
  value     = module.environment.redis_uri
  sensitive = true
}
