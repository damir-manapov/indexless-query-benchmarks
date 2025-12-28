# Timeweb Cloud Terraform Configuration

Terraform configuration for deploying benchmark infrastructure on [Timeweb Cloud](https://timeweb.cloud/).

## Prerequisites

1. [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.0
2. Timeweb Cloud account
3. API token from [API Keys page](https://timeweb.cloud/my/api-keys)

## Setup

1. Export your API token:

```bash
export TWC_TOKEN="your-api-token-here"
```

2. Copy and edit the variables file:

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your desired configuration
```

3. Initialize Terraform:

```bash
terraform init
```

## Usage

### Create infrastructure

```bash
terraform plan
terraform apply
```

### Connect to the VM

```bash
# Get SSH command
terraform output ssh_command

# Or directly
ssh root@$(terraform output -raw vm_ip)
```

### Wait for setup completion

```bash
eval $(terraform output -raw wait_for_ready)
```

### Destroy infrastructure

```bash
terraform destroy
```

## Configuration Options

| Variable              | Default                 | Description                         |
| --------------------- | ----------------------- | ----------------------------------- |
| `environment_name`    | `test`                  | Name suffix for resources           |
| `location`            | `ru-1`                  | Datacenter (ru-1, ru-2, pl-1, kz-1) |
| `cpu_count`           | `12`                    | Number of vCPUs                     |
| `ram_gb`              | `96`                    | RAM in GB                           |
| `disk_size_gb`        | `200`                   | Disk size in GB                     |
| `disk_type`           | `nvme`                  | Disk type (nvme, ssd, hdd)          |
| `ssh_public_key_path` | `~/.ssh/id_ed25519.pub` | Path to SSH public key              |

## Firewall Rules

The following ports are opened:

- 22 (SSH)
- 8080 (Trino UI)
- 9000 (MinIO API)
- 9001 (MinIO Console)
- 8123 (ClickHouse HTTP)
- 3000 (DuckDB)

## Cloud-init

The VM is automatically configured with:

- Docker
- Node.js 24 + pnpm
- warp (MinIO benchmark tool)
- Clones and installs `indexless-query-benchmarks` repo
- A `/root/benchmark-ready` marker file created when setup is complete
