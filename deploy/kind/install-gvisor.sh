#!/usr/bin/env bash
# Registers the gVisor (runsc) runtime with containerd on every kind node
# labelled sandbox=true, then restarts containerd there.
#
# Why a script instead of kind's containerdConfigPatches: the CRI plugin's
# config key changed between containerd 1.x and 2.x, and kind node images
# have shipped both. This detects which one the node runs.
set -euo pipefail

CLUSTER="${CLUSTER:-sentinel}"

nodes="$(kubectl get nodes -l sandbox=true -o jsonpath='{.items[*].metadata.name}')"
if [[ -z "${nodes}" ]]; then
  echo "No nodes labelled sandbox=true in cluster ${CLUSTER}" >&2
  exit 1
fi

for node in ${nodes}; do
  echo "==> ${node}"

  if docker exec "${node}" grep -q 'runtimes.runsc' /etc/containerd/config.toml; then
    echo "    runsc already registered, skipping"
    continue
  fi

  docker exec "${node}" test -x /usr/local/bin/runsc \
    || { echo "    /usr/local/bin/runsc missing: is gVisor installed on the host?" >&2; exit 1; }

  major="$(docker exec "${node}" containerd --version | sed -E 's/.* v?([0-9]+)\..*/\1/')"
  if [[ "${major}" -ge 2 ]]; then
    plugin='io.containerd.cri.v1.runtime'
  else
    plugin='io.containerd.grpc.v1.cri'
  fi
  echo "    containerd ${major}.x -> plugin ${plugin}"

  docker exec -i "${node}" sh -c 'cat >> /etc/containerd/config.toml' <<EOF

# --- gVisor, added by deploy/kind/install-gvisor.sh ---
[plugins."${plugin}".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"
EOF

  docker exec "${node}" systemctl restart containerd
  echo "    containerd restarted"
done

echo "==> Waiting for nodes to be Ready"
kubectl wait --for=condition=Ready nodes --all --timeout=120s
