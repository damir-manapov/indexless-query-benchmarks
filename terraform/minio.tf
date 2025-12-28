# MinIO Distributed Cluster - configurable nodes x drives

# Variables for MinIO
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
  default     = 3
}

variable "minio_drive_size_gb" {
  description = "Size of each data drive in GB"
  type        = number
  default     = 200
}

variable "minio_drive_type" {
  description = "Type of disk for MinIO data drives"
  type        = string
  default     = "fast"
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

# MinIO flavor
resource "openstack_compute_flavor_v2" "minio" {
  count = var.minio_enabled ? 1 : 0

  name      = "minio-${var.minio_node_cpu}vcpu-${var.minio_node_ram_gb}gb"
  ram       = var.minio_node_ram_gb * 1024
  vcpus     = var.minio_node_cpu
  disk      = 0
  is_public = false

  lifecycle {
    ignore_changes = [name] # Allow reuse of existing flavors
  }

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# MinIO security group rules
resource "openstack_networking_secgroup_rule_v2" "minio_api" {
  count = var.minio_enabled ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 9000
  port_range_max    = 9000
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

resource "openstack_networking_secgroup_rule_v2" "minio_console" {
  count = var.minio_enabled ? 1 : 0

  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 9001
  port_range_max    = 9001
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.benchmark.id
}

# Boot volumes for MinIO nodes
resource "openstack_blockstorage_volume_v3" "minio_boot" {
  count = var.minio_enabled ? var.minio_node_count : 0

  name              = "minio-${count.index + 1}-boot"
  size              = 50
  image_id          = data.openstack_images_image_v2.ubuntu.id
  volume_type       = "fast.${var.availability_zone}"
  availability_zone = var.availability_zone
}

# Data volumes for MinIO nodes (drives_per_node * node_count total)
resource "openstack_blockstorage_volume_v3" "minio_data" {
  count = var.minio_enabled ? var.minio_node_count * var.minio_drives_per_node : 0

  name              = "minio-${floor(count.index / var.minio_drives_per_node) + 1}-data-${count.index % var.minio_drives_per_node + 1}"
  size              = var.minio_drive_size_gb
  volume_type       = "${var.minio_drive_type}.${var.availability_zone}"
  availability_zone = var.availability_zone

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Network ports for MinIO nodes
resource "openstack_networking_port_v2" "minio" {
  count = var.minio_enabled ? var.minio_node_count : 0

  name           = "minio-${count.index + 1}-port"
  network_id     = openstack_networking_network_v2.benchmark.id
  admin_state_up = true

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.benchmark.id
    ip_address = "10.0.0.${10 + count.index}"
  }

  security_group_ids = [openstack_networking_secgroup_v2.benchmark.id]

  depends_on = [
    selectel_vpc_project_v2.benchmark,
    selectel_iam_serviceuser_v1.benchmark
  ]
}

# Cloud-init for MinIO nodes - generates dynamic /etc/hosts and volume spec
locals {
  # Generate /etc/hosts entries for all nodes
  minio_hosts_entries = join("\n", [
    for i in range(var.minio_node_count) : "      - echo '10.0.0.${10 + i} minio${i + 1}' >> /etc/hosts"
  ])

  # Generate device letters (sdb, sdc, sdd, ...)
  drive_letters = [for i in range(var.minio_drives_per_node) : element(["b", "c", "d", "e", "f", "g", "h", "i", "j"], i)]

  # Generate format commands
  minio_format_cmds = join("\n", [
    for letter in local.drive_letters : "      - mkfs.xfs -f /dev/sd${letter}"
  ])

  # Generate mkdir command
  minio_mkdir_cmd = "      - mkdir -p ${join(" ", [for i in range(1, var.minio_drives_per_node + 1) : "/data${i}"])}"

  # Generate mount commands
  minio_mount_cmds = join("\n", [
    for i in range(var.minio_drives_per_node) : "      - mount /dev/sd${local.drive_letters[i]} /data${i + 1}"
  ])

  # Generate fstab entries
  minio_fstab_cmds = join("\n", [
    for i in range(var.minio_drives_per_node) : "      - echo '/dev/sd${local.drive_letters[i]} /data${i + 1} xfs defaults,noatime 0 2' >> /etc/fstab"
  ])

  # Generate chown commands
  minio_chown_dirs = join(" ", [for i in range(1, var.minio_drives_per_node + 1) : "/data${i}"])

  # MinIO volume spec: http://minio{1...N}:9000/data{1...M}
  minio_volume_spec = "http://minio{1...${var.minio_node_count}}:9000/data{1...${var.minio_drives_per_node}}"

  minio_cloud_init = <<-EOF
    #cloud-config
    package_update: true

    packages:
      - wget
      - xfsprogs

    runcmd:
      # Add hostnames for MinIO cluster (required for single erasure set)
${local.minio_hosts_entries}

      # Format data drives
${local.minio_format_cmds}

      # Create mount points
${local.minio_mkdir_cmd}

      # Mount drives
${local.minio_mount_cmds}

      # Add to fstab
${local.minio_fstab_cmds}

      # Install MinIO server and client
      - wget -q https://dl.min.io/server/minio/release/linux-amd64/minio -O /usr/local/bin/minio
      - wget -q https://dl.min.io/client/mc/release/linux-amd64/mc -O /usr/local/bin/mc
      - chmod +x /usr/local/bin/minio /usr/local/bin/mc

      # Create minio user
      - useradd -r -s /sbin/nologin minio-user
      - chown -R minio-user:minio-user ${local.minio_chown_dirs}

      # Create MinIO environment file
      - |
        cat > /etc/default/minio << 'ENVFILE'
        MINIO_ROOT_USER="${var.minio_root_user}"
        MINIO_ROOT_PASSWORD="${var.minio_root_password}"
        MINIO_VOLUMES="${local.minio_volume_spec}"
        MINIO_OPTS="--console-address :9001"
        ENVFILE

      # Create systemd service
      - |
        cat > /etc/systemd/system/minio.service << 'SERVICE'
        [Unit]
        Description=MinIO
        Documentation=https://min.io/docs/minio
        Wants=network-online.target
        After=network-online.target

        [Service]
        User=minio-user
        Group=minio-user
        EnvironmentFile=/etc/default/minio
        ExecStart=/usr/local/bin/minio server $MINIO_VOLUMES $MINIO_OPTS
        Restart=always
        RestartSec=5
        LimitNOFILE=65536

        [Install]
        WantedBy=multi-user.target
        SERVICE

      # Start MinIO
      - systemctl daemon-reload
      - systemctl enable minio
      - systemctl start minio

      # Create ready marker
      - touch /root/minio-ready

    final_message: "MinIO node ready after $UPTIME seconds"
  EOF
}

# MinIO compute instances
resource "openstack_compute_instance_v2" "minio" {
  count = var.minio_enabled ? var.minio_node_count : 0

  name              = "minio-${count.index + 1}"
  flavor_id         = openstack_compute_flavor_v2.minio[0].id
  key_pair          = selectel_vpc_keypair_v2.benchmark.name
  availability_zone = var.availability_zone
  user_data         = local.minio_cloud_init

  network {
    port = openstack_networking_port_v2.minio[count.index].id
  }

  # Boot volume
  block_device {
    uuid                  = openstack_blockstorage_volume_v3.minio_boot[count.index].id
    source_type           = "volume"
    destination_type      = "volume"
    boot_index            = 0
    delete_on_termination = true
  }

  # Data volumes (dynamic based on drives_per_node)
  dynamic "block_device" {
    for_each = range(var.minio_drives_per_node)
    content {
      uuid                  = openstack_blockstorage_volume_v3.minio_data[count.index * var.minio_drives_per_node + block_device.value].id
      source_type           = "volume"
      destination_type      = "volume"
      boot_index            = block_device.value + 1
      delete_on_termination = false
    }
  }

  lifecycle {
    ignore_changes = [image_id]
  }

  vendor_options {
    ignore_resize_confirmation = true
  }

  depends_on = [openstack_networking_router_interface_v2.benchmark]
}

# Note: MinIO is accessed via private network from benchmark VM
# No separate floating IP needed - use ssh tunnel or access from benchmark VM

# Outputs
output "minio_internal_endpoints" {
  description = "MinIO internal endpoints for Trino"
  value       = var.minio_enabled ? [for i in range(var.minio_node_count) : "http://10.0.0.${10 + i}:9000"] : null
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
  value       = var.minio_enabled ? "ssh -L 9001:10.0.0.10:9001 -L 9000:10.0.0.10:9000 root@${openstack_networking_floatingip_v2.benchmark.address}" : null
}
