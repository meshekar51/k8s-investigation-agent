variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "bedrock_inference_profile_id" {
  description = "Cross-region inference profile the agent may call, e.g. eu.anthropic.claude-sonnet-5-5"
  type        = string
  default     = "eu.anthropic.claude-sonnet-5-5"

  validation {
    condition     = can(regex("^(eu|us|global|apac|jp|au|in)\\.anthropic\\.", var.bedrock_inference_profile_id))
    error_message = "Use an inference profile id (eu./global. prefix), not a bare model id."
  }
}

variable "github_repo" {
  description = "owner/repo that may assume the CI role through GitHub OIDC, e.g. meshekar51/k8s-sre-agent"
  type        = string
}

variable "create_github_oidc_provider" {
  description = "Set false if token.actions.githubusercontent.com already exists as an IAM OIDC provider in this account."
  type        = bool
  default     = true
}

variable "enable_invocation_logging" {
  description = "Account-wide Bedrock model invocation logging to CloudWatch (one per region)."
  type        = bool
  default     = true
}

variable "budget_email" {
  description = "Where budget alerts go."
  type        = string
}

variable "monthly_budget_usd" {
  type    = number
  default = 30
}
