# Environment
variable "environment_name" {
  description = "Name suffix for resources (e.g., 'fast-ssd-96gb')"
  type        = string
  default     = "test"
}

variable "location" {
  description = "Timeweb Cloud location (ru-1, ru-2, pl-1, kz-1)"
  type        = string
  default     = "ru-1"

  validation {
    condition     = contains(["ru-1", "ru-2", "pl-1", "kz-1"], var.location)
    error_message = "location must be one of: ru-1, ru-2, pl-1, kz-1"
  }
}

# VM Configuration
variable "cpu_count" {
  description = "Number of vCPUs"
  type        = number
  default     = 12
}

variable "ram_gb" {
  description = "RAM in GB"
  type        = number
  default     = 96
}

variable "disk_size_gb" {
  description = "Boot disk size in GB"
  type        = number
  default     = 200
}

variable "disk_type" {
  description = "Disk type: nvme, ssd, hdd"
  type        = string
  default     = "nvme"

  validation {
    condition     = contains(["nvme", "ssd", "hdd"], var.disk_type)
    error_message = "disk_type must be one of: nvme, ssd, hdd"
  }
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key file"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}
