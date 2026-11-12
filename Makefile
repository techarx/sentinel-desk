SHELL := /bin/bash
# No -u: over SSH, bash sources /etc/bash.bashrc, which reads the unset PS1.
.SHELLFLAGS := -eo pipefail -c
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
up: cluster gvisor platform secrets argocd ## Build everything from scratch
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

.PHONY: secrets
secrets: ## Create data-store passwords as Secrets (generated once, kept on the dev machine, never in Git)
	./scripts/secrets.sh

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
	host="$$(uname -r)"; echo "host kernel=$$host"; \
	if grep -qi 'gvisor' <<<"$$out" && ! grep -q "kernel=$$host" <<<"$$out"; then \
	  echo "PASS: pod ran under gVisor (it sees gVisor's kernel, not the host's)"; \
	else echo "FAIL: pod did not run under gVisor"; exit 1; fi
	kubectl delete pod -n sandbox gvisor-smoke

.PHONY: verify-storage
verify-storage: ## Write (first run) or find (later runs) a marker on persistent storage
	kubectl delete pod -n data storage-smoke --ignore-not-found
	kubectl apply -f deploy/tests/storage-smoke.yaml
	kubectl wait -n data --for=jsonpath='{.status.phase}'=Succeeded pod/storage-smoke --timeout=120s
	kubectl logs -n data storage-smoke
	kubectl delete pod -n data storage-smoke
	@echo "Run 'make down && make up && make verify-storage': it should print FOUND with the same time."

# ---------------------------------------------------------------------------
##@ Database (run on the dev machine)
# ---------------------------------------------------------------------------

.PHONY: db-test
db-test: ## Test migrations against a throwaway Postgres in Docker (same as CI)
	./scripts/db-test.sh

.PHONY: er-diagram
er-diagram: ## Regenerate docs/data-model.md (Mermaid ER diagram) from the migrations
	ER_OUT=docs/data-model.md ./scripts/db-test.sh

.PHONY: psql
psql: ## Open psql in the cluster as the schema owner
	kubectl -n data exec -it sentinel-pg-1 -c postgres -- \
	  env PGPASSWORD="$$(kubectl -n data get secret pg-app-credentials -o jsonpath='{.data.password}' | base64 -d)" \
	  psql -h sentinel-pg-rw -U sentinel -d sentinel

.PHONY: db-status
db-status: ## Show the applied migration and the db-migrate Job's last run
	@kubectl -n data exec sentinel-pg-1 -c postgres -- psql -U postgres -d sentinel -tAc "select 'revision: ' || version_num from alembic_version" 2>/dev/null || echo "no migrations applied yet"
	@kubectl -n data get job db-migrate -o custom-columns=JOB:.metadata.name,COMPLETIONS:.status.succeeded,FAILED:.status.failed,IMAGE:.spec.template.spec.containers[0].image 2>/dev/null || true

.PHONY: ingest
ingest: ## Run EDGAR ingestion now (a one-off Job from the ingest-edgar CronJob) and follow its log
	@job=ingest-edgar-manual-$$(date +%s); \
	kubectl -n data create job $$job --from=cronjob/ingest-edgar >/dev/null && echo "Started $$job"; \
	kubectl -n data wait --for=condition=Ready pod -l job-name=$$job --timeout=300s >/dev/null && \
	kubectl -n data logs -f job/$$job

.PHONY: ingest-status
ingest-status: ## Filings, sections and chunks per bank (Postgres) and documents in OpenSearch
	@kubectl -n data exec sentinel-pg-1 -c postgres -- psql -U postgres -d sentinel -c "\
	  SELECT f.ticker, count(DISTINCT f.id) AS filings, count(DISTINCT s.id) AS sections, \
	         count(c.id) AS chunks, count(e.chunk_id) AS embedded \
	    FROM filings f LEFT JOIN sections s ON s.filing_id = f.id \
	    LEFT JOIN chunks c ON c.section_id = s.id LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id \
	   GROUP BY ROLLUP (f.ticker) ORDER BY f.ticker NULLS LAST;"
	@pw=$$(kubectl -n data get secret opensearch-admin -o jsonpath='{.data.password}' | base64 -d); \
	kubectl -n data exec opensearch-cluster-master-0 -c opensearch -- \
	  curl -sk -u "admin:$$pw" "https://localhost:9200/_cat/count/chunks?h=count" | xargs echo "OpenSearch chunks index documents:"

DATA_DIR := /var/lib/sentinel-data

.PHONY: data-reset
data-reset: ## DELETE all persistent data (Postgres, OpenSearch, Redis, Neo4j). Needs CONFIRM=yes
	@test "$(CONFIRM)" = "yes" || { echo "This deletes everything under $(DATA_DIR). Re-run with CONFIRM=yes"; exit 1; }
	@if kind get clusters 2>/dev/null | grep -qx $(CLUSTER); then echo "Run 'make down' first so no database is using the files."; exit 1; fi
	sudo find $(DATA_DIR) -mindepth 1 -delete
	@echo "Data wiped. 'make up' starts with empty stores."

.PHONY: status
status: ## Show nodes, Argo CD apps and the RuntimeClass
	kubectl get nodes -L sandbox,workload
	kubectl get runtimeclass
	kubectl get storageclass
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
	shellcheck infra/devbox/bootstrap.sh deploy/kind/install-gvisor.sh scripts/*.sh

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n"} \
	  /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
