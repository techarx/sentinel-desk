SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

CLUSTER      ?= sentinel
DEVBOX_DIR   := infra/devbox
TF           := terraform -chdir=$(DEVBOX_DIR)
ARGOCD_NS    := argocd

# ---------------------------------------------------------------------------
##@ Dev machine (run on your Mac)
# ---------------------------------------------------------------------------

.PHONY: devbox-up
devbox-up: ## Create the EC2 dev machine, VPC and budget alert
	$(TF) init -upgrade
	$(TF) apply

.PHONY: devbox-ssh-config
devbox-ssh-config: ## Print the ~/.ssh/config block for the dev machine
	@$(TF) output -raw ssh_config

.PHONY: devbox-stop
devbox-stop: ## Stop the dev machine (disk is kept; compute billing stops)
	aws ec2 stop-instances --region $$($(TF) output -raw region) --instance-ids $$($(TF) output -raw instance_id)

.PHONY: devbox-start
devbox-start: ## Start the dev machine again
	aws ec2 start-instances --region $$($(TF) output -raw region) --instance-ids $$($(TF) output -raw instance_id)

.PHONY: devbox-down
devbox-down: ## Destroy the dev machine, its disk and its VPC
	$(TF) destroy

# ---------------------------------------------------------------------------
##@ Cluster (run on the dev machine)
# ---------------------------------------------------------------------------

.PHONY: up
up: cluster gvisor platform argocd ## Build everything from scratch
	@echo
	@echo "Cluster ready. Argo CD UI: make argocd-ui"

.PHONY: down
down: ## Delete the kind cluster
	kind delete cluster --name $(CLUSTER)

.PHONY: cluster
cluster:
	@if kind get clusters | grep -qx $(CLUSTER); then \
	  echo "kind cluster $(CLUSTER) already exists"; \
	else \
	  kind create cluster --config deploy/kind/cluster.yaml --wait 120s; \
	fi

.PHONY: gvisor
gvisor:
	CLUSTER=$(CLUSTER) ./deploy/kind/install-gvisor.sh

.PHONY: platform
platform:
	# Applied directly once so the cluster works before Argo CD syncs; Argo CD owns it afterwards.
	kubectl apply -f deploy/platform/

.PHONY: argocd
argocd:
	helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
	helm repo update argo >/dev/null
	helm upgrade --install argocd argo/argo-cd \
	  --namespace $(ARGOCD_NS) --create-namespace \
	  --values deploy/argocd/values.yaml --wait --timeout 10m
	@if grep -q REPO_URL_PLACEHOLDER deploy/argocd/root-app.yaml; then \
	  echo "Skipping root app: run 'make set-repo REPO=https://github.com/<you>/sentinel-desk.git', commit and push first."; \
	else \
	  kubectl apply -f deploy/argocd/root-app.yaml; \
	fi

.PHONY: argocd-ui
argocd-ui: ## Port-forward the Argo CD UI to localhost:8080 and print the admin password
	@echo "admin password: $$(kubectl -n $(ARGOCD_NS) get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
	kubectl -n $(ARGOCD_NS) port-forward svc/argocd-server 8080:80

.PHONY: verify-gvisor
verify-gvisor: ## Run a pod under gVisor and check it reports gVisor's kernel
	kubectl delete pod -n sandbox gvisor-smoke --ignore-not-found
	kubectl apply -f deploy/tests/gvisor-smoke.yaml
	kubectl wait -n sandbox --for=jsonpath='{.status.phase}'=Succeeded pod/gvisor-smoke --timeout=90s
	@out="$$(kubectl logs -n sandbox gvisor-smoke)"; echo "$$out"; \
	if grep -q 'kernel=4.4.0' <<<"$$out"; then echo "PASS: pod ran under gVisor"; \
	else echo "FAIL: pod did not run under gVisor"; exit 1; fi
	kubectl delete pod -n sandbox gvisor-smoke

.PHONY: status
status: ## Show nodes, Argo CD apps and the RuntimeClass
	kubectl get nodes -L sandbox,workload
	kubectl get runtimeclass
	kubectl -n $(ARGOCD_NS) get applications 2>/dev/null || true

# ---------------------------------------------------------------------------
##@ Repo
# ---------------------------------------------------------------------------

.PHONY: set-repo
set-repo: ## Point Argo CD at your Git repo: make set-repo REPO=https://github.com/<you>/sentinel-desk.git
	@test -n "$(REPO)" || { echo "Usage: make set-repo REPO=https://github.com/<you>/sentinel-desk.git"; exit 1; }
	grep -rl REPO_URL_PLACEHOLDER deploy/argocd | xargs sed -i.bak 's#REPO_URL_PLACEHOLDER#$(REPO)#g'
	find deploy/argocd -name '*.bak' -delete
	@echo "Updated. Commit and push, then run 'make argocd' on the dev machine."

.PHONY: lint
lint: ## Run the same checks as CI (needs terraform and shellcheck)
	terraform fmt -check -recursive infra
	shellcheck infra/devbox/bootstrap.sh deploy/kind/install-gvisor.sh

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n"} \
	  /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
