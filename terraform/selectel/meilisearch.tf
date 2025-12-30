# Meilisearch VM
variable "meilisearch_enabled" {
  type        = bool
  default     = false
  description = "Enable Meilisearch VM"
}

variable "meilisearch_cpu" {
  type        = number
  default     = 4
  description = "vCPU count for Meilisearch VM"
}

variable "meilisearch_ram_gb" {
  type        = number
  default     = 8
  description = "RAM in GB for Meilisearch VM"
}

variable "meilisearch_disk_size_gb" {
  type        = number
  default     = 100
  description = "Disk size in GB for Meilisearch VM"
}

variable "meilisearch_disk_type" {
  type        = string
  default     = "fast"
  description = "Disk type: fast (NVMe), universal (SSD), basic"
}

variable "meilisearch_master_key" {
  type        = string
  default     = "benchmark-master-key-change-in-production"
  description = "Meilisearch master key for API authentication"
  sensitive   = true
}

variable "meilisearch_max_indexing_memory" {
  type        = string
  default     = "1Gb"
  description = "Max memory for indexing (e.g., 256Mb, 1Gb, 2Gb)"
}

variable "meilisearch_max_indexing_threads" {
  type        = number
  default     = 0
  description = "Max threads for indexing (0 = auto)"
}

# Meilisearch flavor
resource "openstack_compute_flavor_v2" "meilisearch" {
  count = var.meilisearch_enabled ? 1 : 0

  name      = "meilisearch-${var.environment_name}-${var.meilisearch_cpu}vcpu-${var.meilisearch_ram_gb}gb"
  ram       = var.meilisearch_ram_gb * 1024
  vcpus     = var.meilisearch_cpu
  disk      = 0
  is_public = false
}

# Meilisearch boot volume
resource "openstack_blockstorage_volume_v3" "meilisearch_boot" {
  count = var.meilisearch_enabled ? 1 : 0

  name              = "meilisearch-boot"
  size              = var.meilisearch_disk_size_gb
  image_id          = data.openstack_images_image_v2.ubuntu.id
  volume_type       = "${var.meilisearch_disk_type}.${var.availability_zone}"
  availability_zone = var.availability_zone
}

# Meilisearch port
resource "openstack_networking_port_v2" "meilisearch" {
  count = var.meilisearch_enabled ? 1 : 0

  name           = "meilisearch-port"
  network_id     = openstack_networking_network_v2.benchmark.id
  admin_state_up = true

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.benchmark.id
    ip_address = "10.0.0.40"
  }

  security_group_ids = [openstack_networking_secgroup_v2.benchmark.id]
}

# Meilisearch cloud-init
locals {
  meilisearch_cloud_init = var.meilisearch_enabled ? templatefile(
    "${path.module}/../cloud-init/selectel/meilisearch.yaml.tftpl",
    {
      master_key           = var.meilisearch_master_key
      max_indexing_memory  = var.meilisearch_max_indexing_memory
      max_indexing_threads = var.meilisearch_max_indexing_threads == 0 ? "auto" : tostring(var.meilisearch_max_indexing_threads)
    }
  ) : ""
}

# Meilisearch VM
resource "openstack_compute_instance_v2" "meilisearch" {
  count = var.meilisearch_enabled ? 1 : 0

  name              = "meilisearch-${var.environment_name}"
  flavor_id         = openstack_compute_flavor_v2.meilisearch[0].id
  key_pair          = selectel_vpc_keypair_v2.benchmark.name
  availability_zone = var.availability_zone
  user_data         = local.meilisearch_cloud_init

  block_device {
    uuid                  = openstack_blockstorage_volume_v3.meilisearch_boot[0].id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = true
  }

  network {
    port = openstack_networking_port_v2.meilisearch[0].id
  }

  vendor_options {
    ignore_resize_confirmation = true
  }

  lifecycle {
    ignore_changes = [user_data]
  }
}

# Security group rule for Meilisearch API
resource "openstack_networking_secgroup_rule_v2" "meilisearch_api" {
  count = var.meilisearch_enabled ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 7700
  port_range_max    = 7700
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# Outputs
output "meilisearch_vm_ip" {
  value       = var.meilisearch_enabled ? openstack_networking_port_v2.meilisearch[0].all_fixed_ips[0] : null
  description = "Meilisearch VM internal IP"
}

output "meilisearch_config" {
  value = var.meilisearch_enabled ? {
    cpu                  = var.meilisearch_cpu
    ram_gb               = var.meilisearch_ram_gb
    disk_gb              = var.meilisearch_disk_size_gb
    disk_type            = var.meilisearch_disk_type
    max_indexing_memory  = var.meilisearch_max_indexing_memory
    max_indexing_threads = var.meilisearch_max_indexing_threads
  } : null
  description = "Meilisearch configuration"
}
