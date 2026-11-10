variable "region" {
  description = "AWS region for the dev machine."
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "Dev machine size. r6i.2xlarge = 8 vCPU / 64 GB, enough for kind plus all data stores."
  type        = string
  default     = "r6i.2xlarge"
}

variable "root_volume_gb" {
  description = "Root disk size. Container images and data stores need room."
  type        = number
  default     = 150
}

variable "ssh_public_key" {
  description = "Your SSH public key (contents of ~/.ssh/id_ed25519.pub). SSH runs over SSM; no port is opened."
  type        = string
}

variable "alert_email" {
  description = "Email address that receives AWS Budgets alerts."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly budget for everything tagged Project=sentinel-desk."
  type        = number
  default     = 150
}

variable "vpc_cidr" {
  description = "CIDR block for the dev VPC."
  type        = string
  default     = "10.40.0.0/16"
}
