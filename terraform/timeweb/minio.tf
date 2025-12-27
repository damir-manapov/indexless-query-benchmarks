# MinIO Distributed Cluster for Timeweb Cloud
# Configurable nodes x drives with VPC networking

# Variables for MinIO cluster
variable "minio_enabled" {
  description = "Enable MinIO cluster deployment"
  type        = bool
  default     = false
}

variable "minio_node_count" {
  description = "Number of MinIO nodes"
  type        = number
  default     = 2
}

variable "minio_node_cpu" {
  description = "CPU cores per MinIO node"
  type        = number
  default     = 4
}

variable "minio_node_ram_gb" {
  description = "RAM in GB per MinIO node"
  type        = number
  default     = 16
}

variable "minio_drives_per_node" {
  description = "Number of data drives per MinIO node"
  type        = number
  default     = 2
}

variable "minio_drive_size_gb" {
  description = "Size of each data drive in GB"
  type        = number
  default     = 100
}

variable "minio_drive_type" {
  description = "Type of disk for MinIO data drives (nvme, ssd, hdd)"
  type        = string
  default     = "nvme"
}

variable "minio_root_user" {
  description = "MinIO root user"
  type        = string
  default     = "minioadmin"
}

variable "minio_root_password" {
  description = "MinIO root password"
  type        = string
  sensitive   = true
  default     = "minioadmin123"
}

# Get configurator for MinIO nodes
data "twc_configurator" "minio" {
  count     = var.minio_enabled ? 1 : 0
  location  = var.location
  disk_type = var.minio_drive_type
}

# Create VPC for MinIO private network
resource "twc_vpc" "minio" {
  count       = var.minio_enabled ? 1 : 0
  name        = "minio-vpc-${var.environment_name}"
  description = "Private network for MinIO cluster"
  subnet_v4   = "10.0.0.0/24"
  location    = var.location
}

# Cloud-init template for MinIO nodes
locals {
  drive_letters     = ["b", "c", "d", "e", "f", "g", "h", "i", "j"]
  minio_volume_spec = "http://minio{1...${var.minio_node_count}}:9000/data{1...${var.minio_drives_per_node}}"
}

# MinIO node servers
resource "twc_server" "minio" {
  count = var.minio_enabled ? var.minio_node_count : 0

  name  = "minio-${count.index + 1}-${var.environment_name}"
  os_id = data.twc_os.ubuntu.id

  configuration {
    configurator_id = data.twc_configurator.minio[0].id
    cpu             = var.minio_node_cpu
    ram             = var.minio_node_ram_gb * 1024
    disk            = 50 * 1024 # 50GB boot disk
  }

  ssh_keys_ids = [twc_ssh_key.benchmark.id]
  project_id   = twc_project.benchmark.id

  # Connect to VPC with static IP
  local_network {
    id = twc_vpc.minio[0].id
    ip = "10.0.0.${10 + count.index}"
  }

  cloud_init = templatefile("${path.module}/minio-cloud-init.yaml", {
    node_count      = var.minio_node_count
    drives_per_node = var.minio_drives_per_node
    drive_letters   = local.drive_letters
    volume_spec     = local.minio_volume_spec
    root_user       = var.minio_root_user
    root_password   = var.minio_root_password
  })
}

# Add IPv4 to first MinIO node (for external access)
resource "twc_server_ip" "minio_ipv4" {
  count            = var.minio_enabled ? 1 : 0
  source_server_id = twc_server.minio[0].id
  type             = "ipv4"
}

# Data drives for MinIO nodes
resource "twc_server_disk" "minio_data" {
  count = var.minio_enabled ? var.minio_node_count * var.minio_drives_per_node : 0

  source_server_id = twc_server.minio[floor(count.index / var.minio_drives_per_node)].id
  size             = var.minio_drive_size_gb * 1024
}

# Firewall for MinIO nodes
resource "twc_firewall" "minio" {
  count = var.minio_enabled ? 1 : 0
  name  = "minio-firewall-${var.environment_name}"

  dynamic "link" {
    for_each = twc_server.minio
    content {
      id   = link.value.id
      type = "server"
    }
  }
}

resource "twc_firewall_rule" "minio_ssh" {
  count       = var.minio_enabled ? 1 : 0
  firewall_id = twc_firewall.minio[0].id
  direction   = "ingress"
  port        = 22
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

resource "twc_firewall_rule" "minio_api_cluster" {
  count       = var.minio_enabled ? 1 : 0
  firewall_id = twc_firewall.minio[0].id
  direction   = "ingress"
  port        = 9000
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

resource "twc_firewall_rule" "minio_console_cluster" {
  count       = var.minio_enabled ? 1 : 0
  firewall_id = twc_firewall.minio[0].id
  direction   = "ingress"
  port        = 9001
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# Outputs for MinIO cluster
output "minio_internal_endpoints" {
  description = "MinIO internal endpoints"
  value       = var.minio_enabled ? [for i in range(var.minio_node_count) : "http://10.0.0.${10 + i}:9000"] : null
}

output "minio_external_ip" {
  description = "MinIO node 1 external IP for access"
  value       = var.minio_enabled && length(twc_server_ip.minio_ipv4) > 0 ? twc_server_ip.minio_ipv4[0].ip : null
}

output "minio_credentials" {
  description = "MinIO credentials"
  value = var.minio_enabled ? {
    access_key = var.minio_root_user
    secret_key = "Use minio_root_password variable"
  } : null
}

output "minio_ssh_tunnel" {
  description = "SSH tunnel command to access MinIO console"
  value       = var.minio_enabled && length(twc_server_ip.minio_ipv4) > 0 ? "ssh -L 9001:10.0.0.10:9001 -L 9000:10.0.0.10:9000 root@${twc_server_ip.minio_ipv4[0].ip}" : null
}

output "minio_cluster_spec" {
  description = "MinIO cluster specification"
  value = var.minio_enabled ? {
    nodes           = var.minio_node_count
    cpu_per_node    = var.minio_node_cpu
    ram_per_node_gb = var.minio_node_ram_gb
    drives_per_node = var.minio_drives_per_node
    drive_size_gb   = var.minio_drive_size_gb
    drive_type      = var.minio_drive_type
    total_drives    = var.minio_node_count * var.minio_drives_per_node
    total_storage   = var.minio_node_count * var.minio_drives_per_node * var.minio_drive_size_gb
  } : null
}
