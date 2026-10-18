# ---------------------------------------------------------------- step 7: identity
# The kind cluster is not on AWS, so the agent needs an AWS identity of its own:
#   - IAM user "sre-agent-kind"   -> the agent pods in kind (keys in Secret sre-agent-aws)
#   - IAM role "sre-agent-github" -> GitHub Actions via OIDC (no stored keys) for evals + e2e
# Both may ONLY call the approved Claude inference profile and the guardrail. Nothing else.

data "aws_caller_identity" "current" {}

locals {
  profile_arn = "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_inference_profile_id}"
}

data "aws_iam_policy_document" "bedrock_invoke" {
  # Call Claude only through the approved inference profile...
  statement {
    sid       = "InvokeViaInferenceProfile"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [local.profile_arn]
  }
  # ...which routes to the foundation model in several EU regions.
  statement {
    sid       = "InvokeFoundationModelOnlyThroughProfile"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:*::foundation-model/*"]
    condition {
      test     = "StringLike"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.profile_arn]
    }
  }
  statement {
    sid       = "UseGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.agent.guardrail_arn]
  }
}

# ---------------------------------------------------------------- agent in kind
resource "aws_iam_user" "kind_agent" {
  name = "sre-agent-kind"
}

resource "aws_iam_user_policy" "kind_agent" {
  name   = "bedrock-invoke-only"
  user   = aws_iam_user.kind_agent.name
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}
# Access keys are created with the AWS CLI (README step 4) so they never land in Terraform state.

# ---------------------------------------------------------------- GitHub Actions (OIDC)
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github" {
  name                 = "sre-agent-github"
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "github" {
  name   = "bedrock-invoke-only"
  role   = aws_iam_role.github.id
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}
