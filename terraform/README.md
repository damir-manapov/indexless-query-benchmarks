# Terraform for Benchmark VMs

Provision Selectel VMs for running benchmarks with different hardware configurations.

## Prerequisites

1. [Terraform](https://terraform.io/downloads) >= 1.0
2. Selectel account with API access
3. SSH key uploaded to Selectel

## Setup

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your credentials:

- `selectel_domain` - Your account ID from https://my.selectel.ru/profile/apikeys
- `selectel_username` - Your username
- `selectel_password` - Your password
- `ssh_key_name` - Name of your SSH key in Selectel

## Usage

```bash
# Initialize Terraform
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

**Fast SSD, 96GB RAM:**

```hcl
environment_name = "fast-ssd-96gb"
cpu_count        = 12
ram_gb           = 96
disk_type        = "fast"
```

**Universal SSD, 64GB RAM:**

```hcl
environment_name = "universal-64gb"
cpu_count        = 8
ram_gb           = 64
disk_type        = "universal"
```

## What Cloud-Init Does

The VM automatically:

1. Updates packages
2. Installs Docker, Node.js (via nvm), pnpm
3. Clones the benchmark repository
4. Runs `pnpm install`
5. Creates `/root/benchmark-ready` marker when done

After cloud-init completes (~3-5 minutes), you can SSH in and run benchmarks immediately.
