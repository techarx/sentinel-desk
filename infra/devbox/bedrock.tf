# Bedrock access for pods, without long-lived keys (Phase 2, Step 2.6).
#
#   dev machine role ──assume (1 h)──► sentinel-bedrock-invoker ──► InvokeModel on the listed models only
#
# A timer on the dev machine assumes this role every 20 minutes and writes the
# temporary credentials into the Kubernetes Secret "bedrock-credentials", which
# pods read as a file. Containers can't reach the instance metadata service
# (hop limit 1), so they never see the dev machine's own role.
# On EKS (Phase 8), EKS Pod Identity does this natively.

variable "bedrock_models" {
  description = "Foundation models pods may call, via their US cross-region inference profiles (us.<model>)."
  type        = list(string)
  default     = ["anthropic.claude-haiku-4-5-20251001-v1:0"]
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "bedrock_invoker" {
  name                 = "sentinel-bedrock-invoker"
  description          = "Sentinel Desk pods: invoke the allowlisted Bedrock models only"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.devbox.arn }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "bedrock_invoke" {
  name = "invoke-allowlisted-models"
  role = aws_iam_role.bedrock_invoker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "InvokeViaUsInferenceProfilesOnly"
      Effect = "Allow"
      Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = concat(
        # The US cross-region profile (requests stay in US regions)...
        [for m in var.bedrock_models : "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/us.${m}"],
        # ...and the model in the US regions that profile routes to.
        [for m in var.bedrock_models : "arn:aws:bedrock:us-*::foundation-model/${m}"],
      )
    }]
  })
}

# Let the dev machine assume the invoker role (and nothing else new).
resource "aws_iam_role_policy" "devbox_assume_bedrock_invoker" {
  name = "assume-bedrock-invoker"
  role = aws_iam_role.devbox.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = aws_iam_role.bedrock_invoker.arn
    }]
  })
}

output "bedrock_invoker_role_arn" {
  description = "Role the dev machine assumes to mint short-lived Bedrock credentials for pods."
  value       = aws_iam_role.bedrock_invoker.arn
}
