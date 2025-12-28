# Redis Configuration - Single and Sentinel modes

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

# Redis flavor
resource "openstack_compute_flavor_v2" "redis" {
  count = var.redis_enabled ? 1 : 0

  name      = "redis-${var.environment_name}-${var.redis_node_cpu}vcpu-${var.redis_node_ram_gb}gb"
  ram       = var.redis_node_ram_gb * 1024
  vcpus     = var.redis_node_cpu
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

# Security group rule for Redis
resource "openstack_networking_secgroup_rule_v2" "redis" {
  count = var.redis_enabled ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 6379
  port_range_max    = 6379
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

resource "openstack_networking_secgroup_rule_v2" "redis_sentinel" {
  count = var.redis_enabled && var.redis_mode == "sentinel" ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 26379
  port_range_max    = 26379
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# Boot volumes for Redis nodes
resource "openstack_blockstorage_volume_v3" "redis_boot" {
  count = var.redis_enabled ? local.redis_node_count : 0

  name              = "redis-${count.index + 1}-boot"
  size              = 50
  image_id          = data.openstack_images_image_v2.ubuntu.id
  volume_type       = "fast.${var.availability_zone}"
  availability_zone = var.availability_zone
}

# Network ports for Redis nodes (starting at 10.0.0.20)
resource "openstack_networking_port_v2" "redis" {
  count = var.redis_enabled ? local.redis_node_count : 0

  name           = "redis-${count.index + 1}-port"
  network_id     = openstack_networking_network_v2.benchmark.id
  admin_state_up = true

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.benchmark.id
    ip_address = "10.0.0.${20 + count.index}"
  }

  security_group_ids = [openstack_networking_secgroup_v2.benchmark.id]

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Cloud-init for single mode
locals {
  redis_single_cloud_init = templatefile("${path.module}/../redis-single-cloud-init.yaml", {
    maxmemory_mb     = local.redis_maxmemory_mb
    maxmemory_policy = var.redis_maxmemory_policy
    io_threads       = var.redis_io_threads
    persistence      = var.redis_persistence
  })

  redis_sentinel_cloud_init = [
    for i in range(3) : templatefile("${path.module}/../redis-sentinel-cloud-init.yaml", {
      node_index       = i
      node_count       = 3
      maxmemory_mb     = local.redis_maxmemory_mb
      maxmemory_policy = var.redis_maxmemory_policy
      io_threads       = var.redis_io_threads
      persistence      = var.redis_persistence
    })
  ]
}

# Redis compute instances
resource "openstack_compute_instance_v2" "redis" {
  count = var.redis_enabled ? local.redis_node_count : 0

  name              = "redis-${count.index + 1}"
  flavor_id         = openstack_compute_flavor_v2.redis[0].id
  key_pair          = selectel_vpc_keypair_v2.benchmark.name
  availability_zone = var.availability_zone
  user_data = var.redis_mode == "single" ? local.redis_single_cloud_init : local.redis_sentinel_cloud_init[count.index]

  network {
    port = openstack_networking_port_v2.redis[count.index].id
  }

  block_device {
    uuid                  = openstack_blockstorage_volume_v3.redis_boot[count.index].id
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
    mode             = var.redis_mode
    nodes            = local.redis_node_count
    cpu_per_node     = var.redis_node_cpu
    ram_per_node_gb  = var.redis_node_ram_gb
    maxmemory_mb     = local.redis_maxmemory_mb
    maxmemory_policy = var.redis_maxmemory_policy
    io_threads       = var.redis_io_threads
    persistence      = var.redis_persistence
  } : null
}
