# Sentinel Desk

A secure, multi-agent research copilot for a fictional bank's markets desk, running on Kubernetes.
It answers questions over SEC filings and a live stream of synthetic trades, and runs LLM-generated
Python inside a gVisor (or Kata) sandbox, with mTLS, workload identity, fine-grained authorization
and guardrails on every hop.

> Status: **Phase 0 — Foundations** (repo, dev machine, kind cluster, Argo CD, CI).

## Repository layout

| Path | What lives there |
|---|---|
| `services/` | Python services (ingestion, MCP tool servers) |
| `agents/` | LangGraph agents (Planner, Retrieval, Analyst, Compliance) |
| `sidecar-go/` | Go guardrail sidecar (Phase 6) |
| `ui/` | Next.js agent UI (Phase 7) |
| `deploy/kind/` | Local kind cluster config and gVisor setup |
| `deploy/argocd/` | Argo CD root app (app-of-apps) and child apps |
| `deploy/platform/` | Cluster-wide resources: namespaces, RuntimeClass |
| `deploy/tests/` | Smoke tests for the cluster |
| `infra/devbox/` | Terraform for the EC2 dev machine |
| `evals/` | Golden sets and evaluation reports (Phase 2) |
| `docs/adr/` | Architecture Decision Records |

## How the pieces fit (Phase 0)

```
 Mac (editor, git, terraform, aws cli)
   │  terraform apply  ─────────────►  AWS us-east-1: VPC + EC2 dev machine (no inbound ports)
   │  ssh over SSM     ─────────────►  dev machine: Docker + kind (3 nodes) + gVisor
   │  git push         ─► GitHub ◄──── Argo CD in kind pulls deploy/ from the repo
```

## Getting started

### 1. One-time setup on your Mac

```bash
brew install awscli terraform kubectl helm shellcheck
```

Also install the AWS **Session Manager plugin** (signed installer from AWS:
https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
and an SSH key if you don't have one (`ssh-keygen -t ed25519`).

### 2. Create the dev machine

```bash
cp infra/devbox/terraform.tfvars.example infra/devbox/terraform.tfvars   # then edit it
make devbox-up
make devbox-ssh-config   # prints an ~/.ssh/config block; paste it in
```

The first boot runs `infra/devbox/bootstrap.sh` (Docker, kind, kubectl, helm, argocd, gVisor).
It takes ~5 minutes. Check progress with `ssh sentinel-devbox 'tail -f /var/log/sentinel-bootstrap.log'`.

Connect with `ssh sentinel-devbox`, or with VS Code **Remote-SSH** to the same host.

### 3. Build the cluster (on the dev machine)

```bash
git clone https://github.com/<you>/sentinel-desk.git && cd sentinel-desk
make up              # kind cluster + gVisor + Argo CD + root app
make verify-gvisor   # proves a pod really runs under gVisor
```

### 4. Save money

```bash
make devbox-stop     # from the Mac, at the end of every session
make devbox-start    # next time
make devbox-down     # destroys the dev machine and its VPC entirely
```

## Make targets

Run `make help` for the full list.
