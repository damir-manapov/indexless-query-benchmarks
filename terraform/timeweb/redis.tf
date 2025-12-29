# Redis Configuration for Timeweb Cloud
# Single and Sentinel modes with VPC networking

# Variables for Redis
variable "redis_enabled" {
  description = "Enable Redis deployment"
  type        = bool
  default     = false
}

variable "redis_mode" {
  description = "Redis mode: single or sentinel"
  type        = string
  default     = "single"
  validation {
    condition     = contains(["single", "sentinel"], var.redis_mode)
    error_message = "redis_mode must be 'single' or 'sentinel'"
  }
}

variable "redis_node_cpu" {
  description = "CPU cores per Redis node"
  type        = number
  default     = 4
}

variable "redis_node_ram_gb" {
  description = "RAM in GB per Redis node"
  type        = number
  default     = 16
}

variable "redis_maxmemory_policy" {
  description = "Redis maxmemory eviction policy"
  type        = string
  default     = "allkeys-lru"
}

variable "redis_io_threads" {
  description = "Number of Redis I/O threads"
  type        = number
  default     = 2
}

variable "redis_persistence" {
  description = "Redis persistence mode: none or rdb"
  type        = string
  default     = "none"
}

# Calculate number of nodes based on mode
locals {
  redis_node_count = var.redis_mode == "single" ? 1 : 3
  # Use 75% of RAM for Redis maxmemory
  redis_maxmemory_mb = floor(var.redis_node_ram_gb * 1024 * 0.75)
}

# Get configurator for Redis nodes
data "twc_configurator" "redis" {
  count       = var.redis_enabled ? 1 : 0
  location    = var.location
  preset_type = "premium" # Use fast NVMe storage for Redis
}

# Create VPC for Redis private network (reuse MinIO VPC if exists, otherwise create)
resource "twc_vpc" "redis" {
  count       = var.redis_enabled && !var.minio_enabled ? 1 : 0
  name        = "redis-vpc-${var.environment_name}"
  description = "Private network for Redis cluster"
  subnet_v4   = "10.0.0.0/24"
  location    = var.location
}

# Determine which VPC to use
locals {
  redis_vpc_id = var.redis_enabled ? (var.minio_enabled ? twc_vpc.minio[0].id : twc_vpc.redis[0].id) : null
}

# Cloud-init for single mode
locals {
  redis_single_cloud_init = templatefile("${path.module}/../cloud-init/timeweb/redis-single.yaml.tftpl", {
    ssh_public_key   = file(var.ssh_public_key_path)
    maxmemory_mb     = local.redis_maxmemory_mb
    maxmemory_policy = var.redis_maxmemory_policy
    io_threads       = var.redis_io_threads
    persistence      = var.redis_persistence
  })

  redis_sentinel_cloud_init = [
    for i in range(3) : templatefile("${path.module}/../cloud-init/timeweb/redis-sentinel.yaml.tftpl", {
      ssh_public_key   = file(var.ssh_public_key_path)
      node_index       = i
      node_count       = 3
      maxmemory_mb     = local.redis_maxmemory_mb
      maxmemory_policy = var.redis_maxmemory_policy
      io_threads       = var.redis_io_threads
      persistence      = var.redis_persistence
    })
  ]
}

# Redis node servers
resource "twc_server" "redis" {
  count = var.redis_enabled ? local.redis_node_count : 0

  name  = "redis-${count.index + 1}-${var.environment_name}"
  os_id = data.twc_os.ubuntu.id

  configuration {
    configurator_id = data.twc_configurator.redis[0].id
    cpu             = var.redis_node_cpu
    ram             = var.redis_node_ram_gb * 1024
    disk            = 50 * 1024 # 50GB boot disk
  }

  ssh_keys_ids = [twc_ssh_key.benchmark.id]
  project_id   = twc_project.benchmark.id

  # Connect to VPC with static IP (10.0.0.20, 10.0.0.21, 10.0.0.22)
  local_network {
    id = local.redis_vpc_id
    ip = "10.0.0.${20 + count.index}"
  }

  cloud_init = var.redis_mode == "single" ? local.redis_single_cloud_init : local.redis_sentinel_cloud_init[count.index]

  depends_on = [twc_ssh_key.benchmark, twc_vpc.redis, twc_vpc.minio]
}

# Update benchmark VM to connect to Redis VPC
# This is handled dynamically in main.tf local_network block

# Outputs
output "redis_endpoints" {
  description = "Redis endpoints"
  value       = var.redis_enabled ? [for i in range(local.redis_node_count) : "10.0.0.${20 + i}:6379"] : null
}

output "redis_master" {
  description = "Redis master endpoint"
  value       = var.redis_enabled ? "10.0.0.20:6379" : null
}

output "redis_cluster_spec" {
  description = "Redis cluster specification"
  value = var.redis_enabled ? {
    mode        = var.redis_mode
    nodes       = local.redis_node_count
    cpu         = var.redis_node_cpu
    ram_gb      = var.redis_node_ram_gb
    maxmemory   = "${local.redis_maxmemory_mb}MB"
    policy      = var.redis_maxmemory_policy
    io_threads  = var.redis_io_threads
    persistence = var.redis_persistence
  } : null
}
