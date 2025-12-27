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

  # Cloud-init script for initial setup
  cloud_init = <<-EOF
    #cloud-config
    package_update: true
    packages:
      - docker.io
      - docker-compose
      - htop
      - iotop
      - mc
      - git
      - curl
      - wget
      - unzip

    runcmd:
      - systemctl enable docker
      - systemctl start docker
      - usermod -aG docker root
      - touch /root/benchmark-ready
  EOF
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

# MinIO API access rule
resource "twc_firewall_rule" "minio_api" {
  firewall_id = twc_firewall.benchmark.id
  direction   = "ingress"
  port        = 9000
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# MinIO Console access rule
resource "twc_firewall_rule" "minio_console" {
  firewall_id = twc_firewall.benchmark.id
  direction   = "ingress"
  port        = 9001
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# ClickHouse HTTP access rule
resource "twc_firewall_rule" "clickhouse_http" {
  firewall_id = twc_firewall.benchmark.id
  direction   = "ingress"
  port        = 8123
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# DuckDB access rule
resource "twc_firewall_rule" "duckdb" {
  firewall_id = twc_firewall.benchmark.id
  direction   = "ingress"
  port        = 3000
  protocol    = "tcp"
  cidr        = "0.0.0.0/0"
}

# Add IPv4 address to the server
resource "twc_server_ip" "benchmark_ipv4" {
  source_server_id = twc_server.benchmark.id
  type             = "ipv4"
}
