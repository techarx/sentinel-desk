#!/usr/bin/env bash
# Creates the data-store passwords as Kubernetes Secrets, without ever putting
# them in Git (the repo is public).
#
# Passwords are generated once and saved under the persistent data folder
# (root-only), then reused. That matters: after `make down && make up` the
# databases still hold their old passwords, so freshly generated ones would
# lock every client out.
set -euo pipefail

STORE="${SECRETS_DIR:-/var/lib/sentinel-data/.secrets}"
sudo install -d -m 0700 "${STORE}"

# Prints the saved value for $1, generating and saving it on first use.
# OpenSearch requires upper, lower, digit and special characters, so every
# password ends with "Aa1-" after 24 random alphanumerics.
get_or_create() {
  local file="${STORE}/$1"
  if ! sudo test -s "${file}"; then
    local pw
    pw="$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 24)Aa1-"
    printf '%s' "${pw}" | sudo tee "${file}" >/dev/null
    sudo chmod 0600 "${file}"
  fi
  sudo cat "${file}"
}

# kubectl create ... --dry-run | kubectl apply: creates or updates, never fails if it exists.
apply_secret() {
  local ns="$1" name="$2"; shift 2
  kubectl create secret generic "${name}" -n "${ns}" "$@" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "    ${ns}/${name}"
}

echo "==> Namespaces"
kubectl apply -f deploy/platform/namespaces.yaml >/dev/null

echo "==> Secrets (values saved in ${STORE})"
apply_secret data pg-app-credentials --type=kubernetes.io/basic-auth \
  --from-literal=username=sentinel \
  --from-literal=password="$(get_or_create postgres-app)"

apply_secret data opensearch-admin \
  --from-literal=password="$(get_or_create opensearch-admin)"

apply_secret data redis-auth \
  --from-literal=password="$(get_or_create redis)"

apply_secret data neo4j-auth \
  --from-literal=NEO4J_AUTH="neo4j/$(get_or_create neo4j)"

apply_secret monitoring grafana-admin \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="$(get_or_create grafana)"
