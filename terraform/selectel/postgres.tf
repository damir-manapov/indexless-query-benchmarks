# PostgreSQL Configuration for Selectel
# Single and Cluster (Patroni) modes with VPC networking

# Variables for Postgres
variable "postgres_enabled" {
  description = "Enable PostgreSQL deployment"
  type        = bool
  default     = false
}

variable "postgres_mode" {
  description = "PostgreSQL mode: single or cluster (Patroni)"
  type        = string
  default     = "single"
  validation {
    condition     = contains(["single", "cluster"], var.postgres_mode)
    error_message = "postgres_mode must be 'single' or 'cluster'"
  }
}

variable "postgres_cpu" {
  description = "CPU cores per Postgres node"
  type        = number
  default     = 4
}

variable "postgres_ram_gb" {
  description = "RAM in GB per Postgres node"
  type        = number
  default     = 16
}

variable "postgres_disk_size_gb" {
  description = "Disk size in GB per Postgres node"
  type        = number
  default     = 100
}

variable "postgres_disk_type" {
  description = "Disk type: fast or universal"
  type        = string
  default     = "fast"
}

# Calculate number of nodes based on mode
locals {
  postgres_node_count = var.postgres_mode == "single" ? 1 : 3
}

# Postgres flavor
resource "openstack_compute_flavor_v2" "postgres" {
  count = var.postgres_enabled ? 1 : 0

  name      = "postgres-${var.environment_name}-${var.postgres_cpu}vcpu-${var.postgres_ram_gb}gb"
  ram       = var.postgres_ram_gb * 1024
  vcpus     = var.postgres_cpu
  disk      = 0
  is_public = false

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Security group rules for PostgreSQL
resource "openstack_networking_secgroup_rule_v2" "postgres" {
  count = var.postgres_enabled ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 5432
  port_range_max    = 5432
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# Patroni REST API (cluster mode)
resource "openstack_networking_secgroup_rule_v2" "postgres_patroni" {
  count = var.postgres_enabled && var.postgres_mode == "cluster" ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 8008
  port_range_max    = 8008
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# etcd ports (cluster mode)
resource "openstack_networking_secgroup_rule_v2" "postgres_etcd_client" {
  count = var.postgres_enabled && var.postgres_mode == "cluster" ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 2379
  port_range_max    = 2379
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

resource "openstack_networking_secgroup_rule_v2" "postgres_etcd_peer" {
  count = var.postgres_enabled && var.postgres_mode == "cluster" ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 2380
  port_range_max    = 2380
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# Boot volumes for Postgres nodes
resource "openstack_blockstorage_volume_v3" "postgres_boot" {
  count = var.postgres_enabled ? local.postgres_node_count : 0

  name              = "postgres-${count.index + 1}-boot"
  size              = var.postgres_disk_size_gb
  image_id          = data.openstack_images_image_v2.ubuntu.id
  volume_type       = "${var.postgres_disk_type}.${var.availability_zone}"
  availability_zone = var.availability_zone
}

# Network ports for Postgres nodes (starting at 10.0.0.30)
resource "openstack_networking_port_v2" "postgres" {
  count = var.postgres_enabled ? local.postgres_node_count : 0

  name           = "postgres-${count.index + 1}-port"
  network_id     = openstack_networking_network_v2.benchmark.id
  admin_state_up = true

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.benchmark.id
    ip_address = "10.0.0.${30 + count.index}"
  }

  security_group_ids = [openstack_networking_secgroup_v2.benchmark.id]

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Cloud-init templates (Selectel - no ssh_authorized_keys needed)
locals {
  postgres_cloud_init = var.postgres_mode == "single" ? [
    templatefile("${path.module}/../cloud-init/selectel/postgres-single.yaml.tftpl", {})
    ] : [
    for i in range(3) : templatefile("${path.module}/../cloud-init/selectel/postgres-cluster.yaml.tftpl", {
      node_index = i
      node_count = 3
    })
  ]
}

# Postgres compute instances
resource "openstack_compute_instance_v2" "postgres" {
  count = var.postgres_enabled ? local.postgres_node_count : 0

  name              = "postgres-${count.index + 1}"
  flavor_id         = openstack_compute_flavor_v2.postgres[0].id
  key_pair          = selectel_vpc_keypair_v2.benchmark.name
  availability_zone = var.availability_zone
  user_data         = local.postgres_cloud_init[count.index]

  network {
    port = openstack_networking_port_v2.postgres[count.index].id
  }

  block_device {
    uuid                  = openstack_blockstorage_volume_v3.postgres_boot[count.index].id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = true
  }

  lifecycle {
    ignore_changes = [image_id]
  }

  vendor_options {
    ignore_resize_confirmation = true
  }

  depends_on = [openstack_networking_router_interface_v2.benchmark]
}

# NOTE: No floating IP for Postgres - access via benchmark VM internal network
# This saves quota and matches Redis/MinIO pattern

# Outputs
output "postgres_vm_ip" {
  description = "Private IP of primary PostgreSQL node (access via benchmark VM)"
  value       = var.postgres_enabled ? "10.0.0.30" : null
}

output "postgres_endpoints" {
  description = "PostgreSQL private endpoints"
  value       = var.postgres_enabled ? [for i in range(local.postgres_node_count) : "10.0.0.${30 + i}:5432"] : null
}

output "postgres_primary" {
  description = "PostgreSQL primary endpoint (private)"
  value       = var.postgres_enabled ? "10.0.0.30:5432" : null
}

output "postgres_connection" {
  description = "PostgreSQL connection string (via benchmark VM)"
  value       = var.postgres_enabled ? "postgresql://postgres@10.0.0.30:5432/postgres" : null
}

output "postgres_config" {
  description = "PostgreSQL configuration summary"
  value = var.postgres_enabled ? {
    mode      = var.postgres_mode
    nodes     = local.postgres_node_count
    cpu       = var.postgres_cpu
    ram_gb    = var.postgres_ram_gb
    disk_gb   = var.postgres_disk_size_gb
    disk_type = var.postgres_disk_type
  } : null
}
