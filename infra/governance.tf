# ---------------------------------------------------------------- step 9: governance
# Bedrock Guardrail in front of every model call:
#  - blocks prompt-injection attempts (e.g. a log line saying "ignore your instructions")
#  - masks credentials/PII that may appear in logs before they reach the model or the report
resource "aws_bedrock_guardrail" "agent" {
  name                      = "k8s-sre-agent"
  description               = "Prompt-attack and secret masking for the Kubernetes SRE agent"
  blocked_input_messaging   = "Blocked by guardrail: the request or cluster data looked like a prompt-injection attempt."
  blocked_outputs_messaging = "Blocked by guardrail: the response contained disallowed content."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "MEDIUM"
      output_strength = "NONE" # prompt-attack filtering applies to input only
    }
    tier_config {
      tier_name = "CLASSIC"
    }
  }

  sensitive_information_policy_config {
    pii_entities_config {
      type   = "AWS_ACCESS_KEY"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "AWS_SECRET_KEY"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PASSWORD"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    regexes_config {
      name        = "bearer_tokens"
      description = "JWT / bearer tokens that leak into logs"
      pattern     = "eyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}"
      action      = "ANONYMIZE"
    }
  }
}

resource "aws_bedrock_guardrail_version" "agent" {
  guardrail_arn = aws_bedrock_guardrail.agent.guardrail_arn
  description   = "Published by Terraform"
  skip_destroy  = true
}

# ---------------------------------------------------------------- step 8+9: model invocation logs
# Every prompt + completion is kept for 30 days (audit trail: what did the agent see and say?).
resource "aws_cloudwatch_log_group" "bedrock" {
  count             = var.enable_invocation_logging ? 1 : 0
  name              = "/aws/bedrock/model-invocations"
  retention_in_days = 30
}

data "aws_iam_policy_document" "bedrock_logging_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "bedrock_logging" {
  count              = var.enable_invocation_logging ? 1 : 0
  name               = "bedrock-invocation-logging"
  assume_role_policy = data.aws_iam_policy_document.bedrock_logging_trust.json
}

resource "aws_iam_role_policy" "bedrock_logging" {
  count = var.enable_invocation_logging ? 1 : 0
  name  = "write-invocation-logs"
  role  = aws_iam_role.bedrock_logging[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.bedrock[0].arn}:*"
    }]
  })
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  count = var.enable_invocation_logging ? 1 : 0
  logging_config {
    text_data_delivery_enabled      = true
    image_data_delivery_enabled     = false
    embedding_data_delivery_enabled = false
    video_data_delivery_enabled     = false
    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock[0].name
      role_arn       = aws_iam_role.bedrock_logging[0].arn
    }
  }
  depends_on = [aws_iam_role_policy.bedrock_logging]
}

# ---------------------------------------------------------------- cost guardrail
# Claude on Bedrock is billed through AWS Marketplace under its own service name,
# so this budget watches the whole account instead of filtering on "Amazon Bedrock".
resource "aws_budgets_budget" "agentops" {
  name         = "agentops-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
