# PostgreSQL Configuration for Timeweb Cloud
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
  description = "Disk type: nvme, ssd, hdd"
  type        = string
  default     = "nvme"
}

# Calculate number of nodes based on mode
locals {
  postgres_node_count  = var.postgres_mode == "single" ? 1 : 3
  postgres_preset_type = var.postgres_disk_type == "nvme" ? "premium" : (var.postgres_disk_type == "hdd" ? "standard" : "")
}

# Get configurator for Postgres nodes
data "twc_configurator" "postgres" {
  count       = var.postgres_enabled ? 1 : 0
  location    = var.location
  preset_type = local.postgres_preset_type
}

# VPC for Postgres (reuse MinIO/Redis VPC if available)
resource "twc_vpc" "postgres" {
  count       = var.postgres_enabled && !var.minio_enabled && !var.redis_enabled ? 1 : 0
  name        = "postgres-vpc-${var.environment_name}"
  subnet_v4   = "10.0.0.0/24"
  location    = var.location
  description = "VPC for PostgreSQL"
}

locals {
  postgres_vpc_id = var.postgres_enabled ? (
    var.minio_enabled ? twc_vpc.minio[0].id : (
      var.redis_enabled ? twc_vpc.redis[0].id : twc_vpc.postgres[0].id
    )
  ) : null
}

# Cloud-init templates (Timeweb uses .yaml.tftpl with ssh_authorized_keys)
locals {
  postgres_cloud_init = var.postgres_mode == "single" ? [
    templatefile("${path.module}/../cloud-init/timeweb/postgres-single.yaml.tftpl", {
      ssh_public_key = file(var.ssh_public_key_path)
    })
    ] : [
    for i in range(3) : templatefile("${path.module}/../cloud-init/timeweb/postgres-cluster.yaml.tftpl", {
      ssh_public_key = file(var.ssh_public_key_path)
      node_index     = i
      node_count     = 3
    })
  ]
}

# PostgreSQL nodes
resource "twc_server" "postgres" {
  count = var.postgres_enabled ? local.postgres_node_count : 0

  name  = "postgres-${count.index + 1}-${var.environment_name}"
  os_id = data.twc_os.ubuntu.id

  configuration {
    configurator_id = data.twc_configurator.postgres[0].id
    cpu             = var.postgres_cpu
    ram             = var.postgres_ram_gb * 1024
    disk            = var.postgres_disk_size_gb * 1024
  }

  ssh_keys_ids = [twc_ssh_key.benchmark.id]
  project_id   = twc_project.benchmark.id

  # Connect to VPC with static IP (10.0.0.30, 10.0.0.31, 10.0.0.32)
  local_network {
    id = local.postgres_vpc_id
    ip = "10.0.0.${30 + count.index}"
  }

  cloud_init = local.postgres_cloud_init[count.index]

  depends_on = [twc_ssh_key.benchmark, twc_vpc.postgres, twc_vpc.redis, twc_vpc.minio]
}

# Public IP for first Postgres node (primary)
resource "twc_server_ip" "postgres_ipv4" {
  count            = var.postgres_enabled ? 1 : 0
  source_server_id = twc_server.postgres[0].id
  type             = "ipv4"
}

# Firewall for Postgres (with inline link)
resource "random_id" "postgres_firewall_suffix" {
  count       = var.postgres_enabled ? 1 : 0
  byte_length = 4
}

resource "twc_firewall" "postgres" {
  count = var.postgres_enabled ? 1 : 0
  name  = "postgres-fw-${random_id.postgres_firewall_suffix[0].hex}"

  # Link all Postgres nodes to this firewall
  dynamic "link" {
    for_each = range(local.postgres_node_count)
    content {
      id   = twc_server.postgres[link.value].id
      type = "server"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "twc_firewall_rule" "postgres_ssh" {
  count       = var.postgres_enabled ? 1 : 0
  firewall_id = twc_firewall.postgres[0].id
  direction   = "ingress"
  port        = "22"
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

resource "twc_firewall_rule" "postgres_pg" {
  count       = var.postgres_enabled ? 1 : 0
  firewall_id = twc_firewall.postgres[0].id
  direction   = "ingress"
  port        = "5432"
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# Patroni REST API port (cluster mode)
resource "twc_firewall_rule" "postgres_patroni" {
  count       = var.postgres_enabled && var.postgres_mode == "cluster" ? 1 : 0
  firewall_id = twc_firewall.postgres[0].id
  direction   = "ingress"
  port        = "8008"
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# Outputs
output "postgres_vm_ip" {
  description = "Public IP of primary PostgreSQL node"
  value       = var.postgres_enabled && length(twc_server_ip.postgres_ipv4) > 0 ? twc_server_ip.postgres_ipv4[0].ip : null
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
  description = "PostgreSQL connection string (public)"
  value       = var.postgres_enabled && length(twc_server_ip.postgres_ipv4) > 0 ? "postgresql://postgres@${twc_server_ip.postgres_ipv4[0].ip}:5432/postgres" : null
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
