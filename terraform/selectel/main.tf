terraform {
  required_version = ">= 1.0"

  required_providers {
    selectel = {
      source  = "selectel/selectel"
      version = "~> 7.0"
    }
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
  }
}

# Selectel provider for project management
provider "selectel" {
  domain_name = var.selectel_domain
  username    = var.selectel_username
  password    = var.selectel_password
  auth_region = var.region
  auth_url    = "https://cloud.api.selcloud.ru/identity/v3/"
}

# Create a project for the benchmark VM
resource "selectel_vpc_project_v2" "benchmark" {
  name = "benchmark-${var.environment_name}"

  lifecycle {
    create_before_destroy = true
    ignore_changes        = [name] # Allow reuse even if name differs
  }
}

# Create a user for OpenStack access
resource "selectel_iam_serviceuser_v1" "benchmark" {
  name     = "benchmark-${var.environment_name}"
  password = var.selectel_openstack_password
  role {
    role_name  = "member"
    scope      = "project"
    project_id = selectel_vpc_project_v2.benchmark.id
  }
}

# Add SSH key to the project
resource "selectel_vpc_keypair_v2" "benchmark" {
  name       = "benchmark-key"
  public_key = file(var.ssh_public_key_path)
  user_id    = selectel_iam_serviceuser_v1.benchmark.id
}

# OpenStack provider for compute resources
provider "openstack" {
  auth_url    = "https://cloud.api.selcloud.ru/identity/v3"
  domain_name = var.selectel_domain
  tenant_id   = selectel_vpc_project_v2.benchmark.id
  user_name   = selectel_iam_serviceuser_v1.benchmark.name
  password    = var.selectel_openstack_password
  region      = var.region
}

# Get Ubuntu 24.04 image
data "openstack_images_image_v2" "ubuntu" {
  name        = "Ubuntu 24.04 LTS 64-bit"
  most_recent = true

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Create a custom flavor for the VM
# Per Selectel docs: for arbitrary configs, create a flavor via openstack_compute_flavor_v2
# Note: Flavors persist in OpenStack even after project is deleted, so we use stable naming
resource "openstack_compute_flavor_v2" "benchmark" {
  name      = "optuna-benchmark-${var.cpu_count}vcpu-${var.ram_gb}gb"
  vcpus     = var.cpu_count
  ram       = var.ram_gb * 1024
  disk      = 0 # Using network boot disk
  is_public = false

  lifecycle {
    create_before_destroy = true
    ignore_changes        = [name] # Allow reuse of existing flavors
  }

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Create network
resource "openstack_networking_network_v2" "benchmark" {
  name = "benchmark-network"

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

resource "openstack_networking_subnet_v2" "benchmark" {
  name            = "benchmark-subnet"
  network_id      = openstack_networking_network_v2.benchmark.id
  cidr            = "10.0.0.0/24"
  dns_nameservers = ["188.93.16.19", "188.93.17.19"]
}

# Router for external connectivity
data "openstack_networking_network_v2" "external" {
  external = true

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

resource "openstack_networking_router_v2" "benchmark" {
  name                = "benchmark-router"
  external_network_id = data.openstack_networking_network_v2.external.id
}

resource "openstack_networking_router_interface_v2" "benchmark" {
  router_id = openstack_networking_router_v2.benchmark.id
  subnet_id = openstack_networking_subnet_v2.benchmark.id
}

# Security group
resource "openstack_networking_secgroup_v2" "benchmark" {
  name        = "benchmark-secgroup"
  description = "Security group for benchmark VM"

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

resource "openstack_networking_secgroup_rule_v2" "ssh" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

resource "openstack_networking_secgroup_rule_v2" "trino" {
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 8080
  port_range_max    = 8080
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# Allow all traffic within internal subnet (benchmark VM <-> MinIO nodes)
resource "openstack_networking_secgroup_rule_v2" "internal" {
  direction         = "ingress"
  ethertype         = "IPv4"
  remote_ip_prefix  = "10.0.0.0/24"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# Note: egress rule is created by default, no need to add it

# Boot volume with selected disk type
resource "openstack_blockstorage_volume_v3" "boot" {
  name              = "benchmark-boot"
  size              = var.disk_size_gb
  image_id          = data.openstack_images_image_v2.ubuntu.id
  volume_type       = "${var.disk_type}.${var.availability_zone}"
  availability_zone = var.availability_zone
}

# Compute instance
resource "openstack_compute_instance_v2" "benchmark" {
  name              = "benchmark-${var.environment_name}"
  flavor_id         = openstack_compute_flavor_v2.benchmark.id
  key_pair          = selectel_vpc_keypair_v2.benchmark.name
  availability_zone = var.availability_zone
  user_data         = templatefile("${path.module}/../cloud-init/selectel/benchmark.yaml.tftpl", {})

  network {
    port = openstack_networking_port_v2.benchmark.id
  }

  block_device {
    uuid                  = openstack_blockstorage_volume_v3.boot.id
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

# Create a port explicitly to use for floating IP association
resource "openstack_networking_port_v2" "benchmark" {
  name           = "benchmark-port"
  network_id     = openstack_networking_network_v2.benchmark.id
  admin_state_up = true

  fixed_ip {
    subnet_id = openstack_networking_subnet_v2.benchmark.id
  }

  security_group_ids = [openstack_networking_secgroup_v2.benchmark.id]

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Floating IP - using external_network_id instead of pool
resource "openstack_networking_floatingip_v2" "benchmark" {
  pool = "external-network"

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

resource "openstack_networking_floatingip_associate_v2" "benchmark" {
  floating_ip = openstack_networking_floatingip_v2.benchmark.address
  port_id     = openstack_networking_port_v2.benchmark.id

  depends_on = [openstack_networking_router_interface_v2.benchmark]
}
