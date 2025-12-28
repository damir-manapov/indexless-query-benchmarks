terraform {
  required_version = ">= 1.0"

  required_providers {
    twc = {
      source  = "tf.timeweb.cloud/timeweb-cloud/timeweb-cloud"
      version = "~> 1.6"
    }
  }
}

provider "twc" {
  # Token from environment variable TWC_TOKEN
  # or set here: token = "..."
}

# Get configurator for the specified location and disk type
data "twc_configurator" "benchmark" {
  location  = var.location
  disk_type = var.disk_type
}

# Get Ubuntu 24.04 OS
data "twc_os" "ubuntu" {
  name    = "ubuntu"
  version = "24.04"
}

# Create SSH key
resource "twc_ssh_key" "benchmark" {
  name = "benchmark-key"
  body = file(var.ssh_public_key_path)
}

# Create project for organization
resource "twc_project" "benchmark" {
  name        = "benchmark-${var.environment_name}"
  description = "Benchmark testing project"
}

# Create the benchmark server
resource "twc_server" "benchmark" {
  name  = "benchmark-${var.environment_name}"
  os_id = data.twc_os.ubuntu.id

  configuration {
    configurator_id = data.twc_configurator.benchmark.id
    cpu             = var.cpu_count
    ram             = var.ram_gb * 1024
    disk            = var.disk_size_gb * 1024
  }

  ssh_keys_ids = [twc_ssh_key.benchmark.id]
  project_id   = twc_project.benchmark.id

  # Connect to MinIO VPC if enabled
  dynamic "local_network" {
    for_each = var.minio_enabled ? [1] : []
    content {
      id = twc_vpc.minio[0].id
      ip = "10.0.0.100" # Benchmark VM gets .100 in the VPC
    }
  }

  cloud_init = file("${path.module}/../benchmark-cloud-init.yaml")
}

# Create firewall for the server
resource "twc_firewall" "benchmark" {
  name = "benchmark-firewall"

  link {
    id   = twc_server.benchmark.id
    type = "server"
  }
}

# SSH access rule
resource "twc_firewall_rule" "ssh" {
  firewall_id = twc_firewall.benchmark.id
  direction   = "ingress"
  port        = 22
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# Trino UI access rule
resource "twc_firewall_rule" "trino" {
  firewall_id = twc_firewall.benchmark.id
  direction   = "ingress"
  port        = 8080
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# Add IPv4 address to the server
resource "twc_server_ip" "benchmark_ipv4" {
  source_server_id = twc_server.benchmark.id
  type             = "ipv4"
}
