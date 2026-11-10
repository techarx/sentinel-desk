terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local state for now (git-ignored). Move to an S3 backend before Phase 8.
}

provider "aws" {
  profile = "adfs"
  region  = var.region

  default_tags {
    tags = {
      Project   = "sentinel-desk"
      Component = "devbox"
      ManagedBy = "terraform"
    }
  }
}
