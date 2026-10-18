output "guardrail_id" {
  value = aws_bedrock_guardrail.agent.guardrail_id
}

output "guardrail_version" {
  value = aws_bedrock_guardrail_version.agent.version
}

output "kind_agent_user" {
  description = "Create its access key with: aws iam create-access-key --user-name <this>"
  value       = aws_iam_user.kind_agent.name
}

output "github_role_arn" {
  description = "Put this in the GitHub repository variable AWS_ROLE_ARN"
  value       = aws_iam_role.github.arn
}
