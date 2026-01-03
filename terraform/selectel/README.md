# Selectel Terraform Configuration

Terraform configuration for deploying benchmark infrastructure on [Selectel](https://selectel.ru/) (OpenStack-based).

## Prerequisites

1. [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.0
2. Selectel account
3. API credentials from [API Keys page](https://my.selectel.ru/profile/apikeys)

## Setup

1. Export your credentials:

```bash
export TF_VAR_selectel_domain="123456"
export TF_VAR_selectel_username="your-username"
export TF_VAR_selectel_password="your-password"
export TF_VAR_selectel_openstack_password="your-openstack-password"
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
ssh root@$(terraform output -raw benchmark_vm_ip)
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

| Variable              | Default                 | Description                                   |
| --------------------- | ----------------------- | --------------------------------------------- |
| `environment_name`    | `test`                  | Name suffix for resources                     |
| `region`              | `ru-7`                  | Selectel region                               |
| `availability_zone`   | `ru-7b`                 | Availability zone                             |
| `cpu_count`           | `8`                     | Number of vCPUs                               |
| `ram_gb`              | `8`                     | RAM in GB                                     |
| `disk_size_gb`        | `200`                   | Disk size in GB                               |
| `disk_type`           | `fast`                  | Disk type (fast, universal, basic, basic_hdd) |
| `ssh_public_key_path` | `~/.ssh/id_ed25519.pub` | Path to SSH public key                        |

## Firewall Rules

The following ports are opened on benchmark VM:

- 22 (SSH)
- 8080 (Trino UI)

MinIO cluster (when enabled) adds ports 9000 and 9001 to the security group.

## Cloud-init

The VM is automatically configured with:

- Docker
- Node.js 24 + pnpm
- warp (MinIO benchmark tool)
- Clones and installs `indexless-query-benchmarks` repo
- A `/root/benchmark-ready` marker file created when setup is complete

## OpenStack CLI

For debugging and manual operations (e.g., cleaning up stale flavors):

```bash
# Set environment variables
export OS_AUTH_URL="https://cloud.api.selcloud.ru/identity/v3"
export OS_IDENTITY_API_VERSION=3
export OS_PROJECT_DOMAIN_NAME="$TF_VAR_selectel_domain"
export OS_USER_DOMAIN_NAME="$TF_VAR_selectel_domain"
export OS_PROJECT_ID="$(terraform output -raw project_id)"
export OS_USERNAME="$TF_VAR_selectel_username"
export OS_PASSWORD="$TF_VAR_selectel_password"
export OS_REGION_NAME="ru-7"

# List flavors
openstack flavor list

# List stale benchmark flavors
openstack flavor list | grep benchmark

# Delete stale flavor
openstack flavor delete <flavor-id>

# List volume types
openstack volume type list
```
