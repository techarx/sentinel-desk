# ADR-001: Why this stack

- **Status:** Accepted
- **Date:** 2026-11-10
- **Phase:** 0

## Context

Sentinel Desk runs LLM-generated code and processes adversarial documents next to sensitive
(synthetic) financial data. The stack has to make isolation, identity and authorization
first-class, stay reproducible from Git, and run cheaply for a single developer before
moving to Amazon EKS in Phase 8.

## Decisions

| Area | Choice | Main alternatives | Why |
|---|---|---|---|
| Local Kubernetes | **kind on an EC2 dev machine** (Ubuntu 24.04, r6i.2xlarge) | kind in Lima on a Mac; k3s; minikube | gVisor and Kata need a Linux host. An EC2 machine gives real Linux, 64 GB RAM, and the same cloud as the EKS target. kind is disposable and multi-node. |
| Dev machine access | **SSH tunnelled through SSM Session Manager**, no inbound ports | Public SSH with an IP allowlist; bastion host | No open port, access controlled by IAM and logged in CloudTrail. Matches the project's zero-trust theme. |
| Sandbox runtime | **gVisor (runsc)** via a RuntimeClass; Kata + Firecracker as a stretch | Plain runc with seccomp; Kata only | gVisor needs no hardware virtualization, so it works in kind and on regular EKS nodes. Kata gives a stronger boundary but needs bare metal or nested virtualization. |
| GitOps | **Argo CD, app-of-apps** | Flux; plain `kubectl apply` | The cluster is rebuilt often; Git is the single source of truth. Argo CD's UI makes drift and health visible in demos. |
| Packaging | **Helm for third-party charts, plain YAML / Kustomize for our own** | Helm everywhere | Our manifests stay readable and reviewable; upstream charts are consumed as-is. |
| Infrastructure as code | **Terraform** | CDK; Pulumi; eksctl | Widely used in banks; the same tool covers the dev machine now and EKS in Phase 8. |
| CI | **GitHub Actions** | GitLab CI; Jenkins | Free for this repo; native OIDC to AWS later; supports cosign keyless signing. |
| Languages | **Python** (agents, ML), **Go** (guardrail sidecar), **TypeScript / Next.js** (UI) | Rust sidecar | Python has the agent and ML ecosystem; Go has a fast, simple reverse proxy in its standard library; Next.js supports the AG-UI protocol. |
| Baseline pod security | **Pod Security Admission "restricted"** on app and sandbox namespaces | No baseline until Kyverno | Cheapest control available, on from day one. Kyverno adds stricter rules in Phase 5. |

## Consequences

- **Cost:** the dev machine is about the cost of a coffee per working session if stopped
  between sessions; a budget alert covers everything tagged `Project=sentinel-desk`.
- **Two environments:** kind locally and EKS later differ in networking (kindnet vs VPC CNI),
  load balancing and node provisioning. The same Argo CD apps are reused to keep drift small.
- **gVisor first:** some syscalls are unsupported or slower under gVisor. That is acceptable
  for short pandas jobs and is measured in Phase 4.
- **Single developer:** Terraform state is local until Phase 8, when it moves to S3 with locking.
