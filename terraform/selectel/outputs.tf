output "benchmark_vm_ip" {
  description = "Public IP address of the benchmark VM"
  value       = openstack_networking_floatingip_v2.benchmark.address
}

output "ssh_command" {
  description = "SSH command to connect to the VM"
  value       = "ssh root@${openstack_networking_floatingip_v2.benchmark.address}"
}

output "vm_specs" {
  description = "VM specifications"
  value = {
    cpu       = var.cpu_count
    ram_gb    = var.ram_gb
    disk_type = var.disk_type
    disk_gb   = var.disk_size_gb
    region    = var.region
  }
}

output "project_id" {
  description = "Selectel project ID"
  value       = selectel_vpc_project_v2.benchmark.id
}

output "wait_for_ready" {
  description = "Command to wait for cloud-init to complete"
  value       = "ssh root@${openstack_networking_floatingip_v2.benchmark.address} 'while [ ! -f /root/benchmark-ready ]; do echo \"Waiting for setup...\"; sleep 10; done; echo \"Ready!\"'"
}
