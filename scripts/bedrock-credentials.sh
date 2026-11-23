#!/usr/bin/env bash
# Mints short-lived Bedrock credentials for pods. Runs ON THE DEV MACHINE HOST
# every 20 minutes (systemd timer, see infra/devbox/systemd/), never in a pod.
#
#   host (its own EC2 role) ──assume──► sentinel-bedrock-invoker (1 hour)
#        └─► Kubernetes Secret data/bedrock-credentials (credentials.json)
#              └─► pods read it via credential_process and refresh before expiry
#
# The JSON format is the AWS "credential_process" format, which SDKs refresh
# automatically before its Expiration.
set -euo pipefail

export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_PAGER=""
NAMESPACE=data
SECRET=bedrock-credentials

account=$(aws sts get-caller-identity --query Account --output text)
role="arn:aws:iam::${account}:role/sentinel-bedrock-invoker"

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
chmod 700 "$workdir"

aws sts assume-role \
  --role-arn "$role" \
  --role-session-name "sentinel-pods-$(date +%s)" \
  --duration-seconds 3600 \
  --query Credentials --output json \
  | jq -c '{Version: 1, AccessKeyId, SecretAccessKey, SessionToken, Expiration}' > "$workdir/credentials.json"

# From a file (not --from-literal) so the credentials never appear in a process list.
kubectl -n "$NAMESPACE" create secret generic "$SECRET" \
  --from-file=credentials.json="$workdir/credentials.json" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "$(date -u +%FT%TZ) ${NAMESPACE}/${SECRET} refreshed; expires $(jq -r .Expiration "$workdir/credentials.json")"
