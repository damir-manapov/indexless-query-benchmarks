# Terraform for Benchmark VMs

Provision cloud VMs for running MinIO and Trino benchmarks.

## Structure

```
terraform/
├── check.sh                  # Validation script
├── benchmark-cloud-init.yaml # Shared benchmark VM setup
├── selectel/                 # Selectel (OpenStack-based)
│   ├── main.tf
│   ├── minio.tf
│   ├── outputs.tf
│   ├── variables.tf
│   ├── minio-cloud-init.yaml
│   ├── README.md
│   └── terraform.tfvars.example
└── timeweb/                  # Timeweb Cloud
    ├── main.tf
    ├── minio.tf
    ├── outputs.tf
    ├── variables.tf
    ├── minio-cloud-init.yaml
    ├── README.md
    └── terraform.tfvars.example
```

## Prerequisites

1. [Terraform](https://terraform.io/downloads) >= 1.0
2. [tflint](https://github.com/terraform-linters/tflint) (optional, for linting)
3. [trivy](https://github.com/aquasecurity/trivy) (optional, for security scanning)
4. Cloud account (Selectel or Timeweb)

## Setup

### Selectel

```bash
cd terraform/selectel
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your settings

# Set credentials via environment variables
export TF_VAR_selectel_domain="123456"
export TF_VAR_selectel_username="your-username"
export TF_VAR_selectel_password="your-password"
export TF_VAR_selectel_openstack_password="your-openstack-password"
```

Get credentials from https://my.selectel.ru/profile/apikeys

### Timeweb

```bash
cd terraform/timeweb
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your settings

# Set API token via environment variable
export TWC_TOKEN="your-api-token"
```

## Usage

```bash
# Initialize Terraform
cd terraform/selectel  # or terraform/timeweb
terraform init

# Preview changes
terraform plan

# Create VM
terraform apply

# Get SSH command
terraform output ssh_command

# Wait for cloud-init to complete
eval $(terraform output -raw wait_for_ready)

# SSH and run benchmarks
ssh root@<ip>
cd /root/indexless-query-benchmarks
pnpm compose:reset && pnpm compose:up:trino:64gb && \
  sleep 30 && \
  pnpm generate --trino -n 300_000_000 -b 100_000_000 --env 64gb --report

# Destroy when done
terraform destroy
```

## Configurations

### Disk Types

| Type        | IOPS (read/write) | Throughput |
| ----------- | ----------------- | ---------- |
| `fast`      | 25k/15k           | 500 MB/s   |
| `universal` | up to 16k         | 200 MB/s   |
| `basic`     | 640/320           | 150 MB/s   |
| `basic_hdd` | 320/120           | 100 MB/s   |

### Example Configurations

**Default (small test VM):**

```hcl
environment_name = "test"
cpu_count        = 8
ram_gb           = 8
disk_type        = "fast"
```

**Production benchmark:**

```hcl
environment_name = "benchmark"
cpu_count        = 16
ram_gb           = 64
disk_type        = "fast"
```

## What Cloud-Init Does

The VM automatically:

1. Updates packages
2. Installs Docker, Node.js 24, pnpm
3. Clones the benchmark repository
4. Runs `pnpm install`
5. Creates `/root/benchmark-ready` marker when done

After cloud-init completes (~3-5 minutes), you can SSH in and run benchmarks immediately.

## MinIO Cluster (Optional)

Deploy a production-grade MinIO cluster with erasure coding for S3 storage.

### Configuration

Add to `terraform.tfvars`:

```hcl
minio_enabled       = true
minio_root_password = "your-secure-password"

# Optional overrides
minio_node_cpu        = 4   # vCPU per node (default: 4)
minio_node_ram_gb     = 16  # RAM per node (default: 16)
minio_drives_per_node = 2   # Drives per node (default: 2)
minio_drive_size_gb   = 100 # Per drive (default: 100)
```

### Architecture

- **2 nodes × 2 drives** = 4 drives total (default)
- **Single erasure set** across all drives (EC:2)
- **Usable capacity**: ~50% of raw storage (2 data + 2 parity)
- **Fault tolerance**: Up to 2 drives OR 1 full node

### Access

MinIO is on the private network (no public IP). Access options:

```bash
# SSH tunnel from local machine
ssh -L 9001:10.0.0.10:9001 -L 9000:10.0.0.10:9000 root@<benchmark-vm-ip>

# Then open: http://localhost:9001 (console)
# S3 API: http://localhost:9000
```

From the benchmark VM, use internal endpoints:

- `http://10.0.0.10:9000`
- `http://10.0.0.11:9000`

### Credentials

Default: `minioadmin` / `minioadmin123` (change via `minio_root_password`)
