terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Use your usual S3 remote state (uncomment and fill):
  # backend "s3" {
  #   bucket       = "<your-tf-state-bucket>"
  #   key          = "agentops/k8s-sre-agent.tfstate"
  #   region       = "eu-central-1"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "k8s-sre-agent"
      ManagedBy = "terraform"
    }
  }
}
