output "project_id" {
  description = "Project ID"
  value       = twc_project.benchmark.id
}

output "benchmark_vm_ip" {
  description = "Public IP address of the benchmark VM"
  value       = twc_server_ip.benchmark_ipv4.ip
}

output "ssh_command" {
  description = "SSH command to connect to the benchmark VM"
  value       = "ssh root@${twc_server_ip.benchmark_ipv4.ip}"
}

output "vm_specs" {
  description = "VM specifications"
  value = {
    cpu       = var.cpu_count
    ram_gb    = var.ram_gb
    disk_gb   = var.disk_size_gb
    disk_type = var.disk_type
    location  = var.location
  }
}

output "wait_for_ready" {
  description = "Command to wait for VM setup completion"
  value       = "ssh root@${twc_server_ip.benchmark_ipv4.ip} 'while [ ! -f /root/benchmark-ready ]; do echo \"Waiting for setup...\"; sleep 10; done; echo \"Ready!\"'"
}

output "root_password" {
  description = "Root password (use SSH keys instead)"
  value       = twc_server.benchmark.root_pass
  sensitive   = true
}
