# Selectel Account Credentials
# Set via environment variables:
#   export TF_VAR_selectel_domain="123456"
#   export TF_VAR_selectel_username="your-username"
#   export TF_VAR_selectel_password="your-password"
#   export TF_VAR_selectel_openstack_password="your-openstack-password"

variable "selectel_domain" {
  description = "Selectel account domain (account ID)"
  type        = string
  default     = null
}

variable "selectel_username" {
  description = "Selectel username"
  type        = string
  default     = null
}

variable "selectel_password" {
  description = "Selectel password"
  type        = string
  sensitive   = true
  default     = null
}

variable "selectel_openstack_password" {
  description = "Password for OpenStack service user"
  type        = string
  sensitive   = true
  default     = null
}

# Environment
variable "environment_name" {
  description = "Name suffix for resources (e.g., 'fast-ssd-96gb')"
  type        = string
  default     = "test"
}

variable "region" {
  description = "Selectel region"
  type        = string
  default     = "ru-7"
}

variable "availability_zone" {
  description = "Availability zone"
  type        = string
  default     = "ru-7b"
}

# VM Configuration
variable "cpu_count" {
  description = "Number of vCPUs for benchmark VM"
  type        = number
  default     = 16
}

variable "ram_gb" {
  description = "RAM in GB for benchmark VM (Selectel requires 32GB min for 16 vCPUs)"
  type        = number
  default     = 32
}

variable "disk_size_gb" {
  description = "Boot disk size in GB"
  type        = number
  default     = 200
}

variable "disk_type" {
  description = "Disk type: fast, universal, basic, basic_hdd"
  type        = string
  default     = "fast"

  validation {
    condition     = contains(["fast", "universal", "basic", "basic_hdd"], var.disk_type)
    error_message = "disk_type must be one of: fast, universal, basic, basic_hdd"
  }
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key file"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}
