#!/usr/bin/env bash
# Installs the Phase 0 toolchain on an Ubuntu 24.04 dev machine.
# Safe to re-run. Run as root (cloud-init does this on first boot).
set -euo pipefail

# Pinned versions: bump deliberately, not by accident.
KIND_VERSION="v0.29.0"
HELM_VERSION="v3.17.3"

ARCH="$(dpkg --print-architecture)"   # amd64
export DEBIAN_FRONTEND=noninteractive

echo "==> Base packages"
apt-get update -y
apt-get install -y ca-certificates curl gnupg git make jq unzip python3-venv shellcheck

echo "==> Kernel settings: inotify limits for kind, mmap count for OpenSearch"
cat > /etc/sysctl.d/99-kind.conf <<'EOF'
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
# OpenSearch refuses to start below 262144. kind nodes share this kernel.
vm.max_map_count = 262144
EOF
sysctl --system >/dev/null

echo "==> Persistent data folder for the kind data node (survives make down)"
install -d -m 0755 /var/lib/sentinel-data

echo "==> Docker (official apt repo)"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck source=/dev/null  # system file, not part of this repo
. /etc/os-release
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
usermod -aG docker ubuntu

echo "==> gVisor (runsc + containerd shim, official apt repo)"
curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor --yes -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
  > /etc/apt/sources.list.d/gvisor.list
apt-get update -y
apt-get install -y runsc

echo "==> kind ${KIND_VERSION}"
curl -fsSLo /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${ARCH}"
chmod +x /usr/local/bin/kind

echo "==> kubectl (current stable)"
KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl"
chmod +x /usr/local/bin/kubectl

echo "==> helm ${HELM_VERSION}"
curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH}.tar.gz" | tar -xz -C /tmp
install -m 0755 "/tmp/linux-${ARCH}/helm" /usr/local/bin/helm

echo "==> argocd CLI (latest release)"
curl -fsSLo /usr/local/bin/argocd "https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-${ARCH}"
chmod +x /usr/local/bin/argocd

echo "==> Versions"
docker --version
runsc --version | head -1
kind version
kubectl version --client
helm version --short
argocd version --client --short || true

echo "==> Bootstrap complete"
