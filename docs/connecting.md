# Connecting: dev machine, cluster and UIs

Every command, and **where** to run it. Check your prompt first:

| Prompt | You are on | Project folder |
|---|---|---|
| `mazeez@…` | **Your Mac** | `~/code/projects/sentinel-desk` |
| `ubuntu@ip-10-40-…` | **The dev machine** (after `ssh sentinel-devbox`) | `~/sentinel-desk` |

`make` commands only work from inside the project folder.

---

## 1. Start of a session (Mac)

```bash
cd ~/code/projects/sentinel-desk
```
```bash
export AWS_PROFILE=adfs
```
Refresh your `adfs` login if it has expired (symptom: `403 Forbidden` / `UnauthorizedRequest`). Then:

```bash
make devbox-start
```

Wait ~3 minutes for the machine, then a few more for the cluster's pods.

## 2. Connect to the dev machine (Mac)

```bash
ssh sentinel-devbox
```

This works through SSM (no open ports); see the Phase 0 summary for how. Then, **on the dev machine**:

```bash
cd ~/sentinel-desk && git pull && make status
```
```bash
kubectl get pods -A | grep -v -E "Running|Completed"
```

The second command lists only unhealthy pods; just the header line means all is well.

## 3. End of a session

On the dev machine (if the trade stream is on):
```bash
make stream-stop
```
On the Mac:
```bash
make devbox-stop
```
`make devbox-down` **destroys** the machine and all data. Only use it when finished with the project.

---

## 4. UIs and APIs (tunnels)

Each UI needs a **tunnel**: run the command **on your Mac**, in its **own Terminal window**, and leave it open.
`-t` makes sure Ctrl+C also stops the port-forward on the dev machine.

| What | Tunnel command (Mac) | Then open | Login |
|---|---|---|---|
| **Argo CD** | `ssh -t -L 8080:localhost:8080 sentinel-devbox 'cd ~/sentinel-desk && make argocd-ui'` | http://localhost:8080 | `admin` / printed by the command |
| **Grafana** | `ssh -t -L 3000:localhost:3000 sentinel-devbox 'kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80'` | http://localhost:3000 | `admin` / `grafana` file |
| **Prometheus** | `ssh -t -L 9090:localhost:9090 sentinel-devbox 'kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090'` | http://localhost:9090 | none |
| **Postgres** (DBeaver) | `ssh -t -L 6160:localhost:5432 sentinel-devbox 'kubectl -n data port-forward svc/sentinel-pg-rw 5432:5432'` | DBeaver → `localhost:6160` | see section 5 |
| **Neo4j Browser** | `ssh -t -L 7474:localhost:7474 -L 7687:localhost:7687 sentinel-devbox 'kubectl -n data port-forward svc/neo4j 7474 7687'` | http://localhost:7474, connect to `bolt://localhost:7687` | `neo4j` / `neo4j` file |
| **OpenSearch API** (curl) | `ssh -t -L 9200:localhost:9200 sentinel-devbox 'kubectl -n data port-forward svc/opensearch-cluster-master 9200:9200'` | `curl -k -u "admin:$OS_PW" https://localhost:9200` | `admin` / `opensearch-admin` file |
| **Retrieval API** | `ssh -t -L 8000:localhost:8000 sentinel-devbox 'kubectl -n data port-forward svc/retrieval 8000:8000'` | http://localhost:8000/docs | none |

The ports on the **left** of `-L` (8080, 3000, 6160 …) are on your Mac; change them if something there already uses them.

### Passwords

The "file" in the table is under `/var/lib/sentinel-data/.secrets/` on the dev machine. Print one from your Mac:

```bash
ssh sentinel-devbox 'sudo cat /var/lib/sentinel-data/.secrets/grafana'; echo
```

Swap `grafana` for `neo4j`, `opensearch-admin`, `postgres-app`, `postgres-readonly_analyst`, …

For curl against OpenSearch, load the password into a variable in the **same** Terminal window:

```bash
export OS_PW=$(ssh sentinel-devbox 'sudo cat /var/lib/sentinel-data/.secrets/opensearch-admin')
```

Never paste these passwords into chats, tickets or Git.

---

## 5. DBeaver (Postgres)

**Database → New Database Connection → PostgreSQL**

| Field | Value |
|---|---|
| Host / Port / Database | `localhost` / `6160` / `sentinel` |
| Username / Password | `sentinel` / `postgres-app` file |
| SSL tab | **Use SSL** ✅, mode **`require`**, certificates empty |
| SSH tab | Off (the Terminal tunnel does this) |

Other users, each with its own password file (`postgres-<user>`):

| User | Can |
|---|---|
| `sentinel` | Everything (schema owner) |
| `readonly_analyst` | Read everything except PII columns |
| `ingest_writer` | Write filings and chunks |
| `stream_writer` | Insert trades, update exposures |
| `trade_generator` | Read desks, books, counterparties |

---

## 6. Working with code

Edit on the **Mac**, ship through Git, use on the **dev machine**:

```bash
git add -A && git commit -m "…" && git push      # Mac
```

Wait ~5 minutes (CI builds images, Argo CD polls Git every ~3 minutes; **Refresh** in the Argo CD UI forces it). Then:

```bash
cd ~/sentinel-desk && git pull                    # dev machine
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `403` / `Forbidden` / `UnauthorizedRequest` | AWS login expired: refresh `adfs`, `export AWS_PROFILE=adfs` |
| `TargetNotConnected` | Machine still booting (wait a minute), or stopped (`make devbox-start`) |
| `Address already in use` in the **Mac** window | Another program uses that port: change the left number in `-L` |
| `address already in use` from the **dev machine** | Leftover port-forward: `ssh sentinel-devbox 'pkill -f "port-forward svc/<service>"'` |
| `make: No rule to make target` | You're not in the project folder (or on the wrong machine) |
| `cd: no such file or directory: …/sentinel-desk` | `~/sentinel-desk` exists only on the dev machine; on the Mac it's `~/code/projects/sentinel-desk` |
| A UI loads but data looks stale | Tunnel dropped: Ctrl+C and run it again |
| Pods `CrashLoopBackOff` / `Error` right after start | Usually a start-up race (DNS or databases not ready yet). Wait a few minutes; check `kubectl -n data logs <pod> --previous` |
