#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=false
RUN_SMOKE=false

for ARG in "$@"; do
  case "$ARG" in
    --dry-run) DRY_RUN=true ;;
    --smoke) RUN_SMOKE=true ;;
    *) echo "Unknown argument: $ARG"; exit 1 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

MODEL_NS="${MODEL_NS:-my-first-model}"
MCP_NS="${MCP_NS:-apollo-dev}"
CANARY_NS="${CANARY_NS:-apollo-canary}"
OBS_NS="${OBS_NS:-apollo-observability}"
TRACING_NS="${TRACING_NS:-apollo-tracing}"
ODS_NS="${ODS_NS:-redhat-ods-applications}"
GITOPS_NS="${GITOPS_NS:-openshift-gitops}"

MODEL_ISVC="${MODEL_ISVC:-llama-32-3b-instruct}"
MODEL_ALIAS="${MODEL_ALIAS:-RedHatAI/Llama-3.2-3B-Instruct-FP8}"

GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-$(openssl rand -base64 18 2>/dev/null || date +%s | sha256sum | cut -c1-24)}"

echo "============================================================"
echo "Apollo Agent Lifecycle redeploy"
echo "Repo: $ROOT"
echo "Dry run: $DRY_RUN"
echo "Smoke tests: $RUN_SMOKE"
echo "============================================================"

run() {
  echo "+ $*"
  if [ "$DRY_RUN" = "false" ]; then
    "$@"
  fi
}

apply_file() {
  local file="$1"

  if [ ! -f "$file" ]; then
    echo "SKIP missing file: $file"
    return 0
  fi

  echo
  echo "==> Applying $file"

  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: oc apply -f $file"
    return 0
  fi

  if [ "$file" = "observability/grafana/grafana.yaml" ]; then
    python3 - "$file" <<'PY' | oc apply -f -
import os
import sys
from pathlib import Path

p = Path(sys.argv[1])
text = p.read_text()
text = text.replace("${GRAFANA_ADMIN_PASSWORD}", os.environ["GRAFANA_ADMIN_PASSWORD"])
print(text)
PY
  else
    oc apply -f "$file"
  fi
}

apply_dir() {
  local dir="$1"

  if [ ! -d "$dir" ]; then
    echo "SKIP missing dir: $dir"
    return 0
  fi

  find "$dir" -maxdepth 3 -type f \( -name "*.yaml" -o -name "*.yml" \) | sort | while read -r file; do
    apply_file "$file"
  done
}

wait_for_crd_hint() {
  local pattern="$1"
  local label="$2"

  if oc api-resources | grep -Ei "$pattern" >/dev/null 2>&1; then
    echo "OK - $label API available"
  else
    echo "WARN - $label API not found yet. Operator may be missing or still starting."
  fi
}

echo
echo "==> 1. Preflight"

command -v oc >/dev/null || { echo "ERROR: oc not found"; exit 1; }
oc whoami >/dev/null || { echo "ERROR: not logged in to OpenShift"; exit 1; }

echo "Logged in as: $(oc whoami)"
oc version --client || true

echo
echo "==> 2. Namespaces"

for ns in "$MODEL_NS" "$MCP_NS" "$CANARY_NS" "$OBS_NS" "$TRACING_NS"; do
  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: create namespace $ns"
  else
    oc create namespace "$ns" --dry-run=client -o yaml | oc apply -f -
  fi
done

run oc annotate namespace "$MODEL_NS" openshift.io/display-name="Apollo Agent Lifecycle - Model Project" --overwrite
run oc annotate namespace "$MCP_NS" openshift.io/display-name="Apollo Agent Lifecycle - MCP Backend" --overwrite
run oc annotate namespace "$CANARY_NS" openshift.io/display-name="Apollo Agent Lifecycle - Canary Application" --overwrite
run oc annotate namespace "$OBS_NS" openshift.io/display-name="Apollo Agent Lifecycle - Observability" --overwrite
run oc annotate namespace "$TRACING_NS" openshift.io/display-name="Apollo Agent Lifecycle - Tracing" --overwrite

echo
echo "==> 3. Operators and platform resources"

apply_file "pipelines/operator-subscription.yaml"
apply_file "gitops/rollouts/namespace-scoped-rollouts-subscription.yaml"
apply_file "gitops/rollouts/rollout-manager.yaml"

apply_file "observability/cluster-observability/operator.yaml"
apply_file "observability/cluster-observability/distributed-tracing-uiplugin.yaml"
apply_file "observability/cluster-observability/tempo-dev-reader.yaml"

apply_file "evaluations/trustyai/evalhub-evaluator-rbac.yaml"
apply_file "evaluations/trustyai/evalhub.yaml"
apply_file "evaluations/trustyai/dashboard-workaround/evalhub-dashboard-user-rbac.yaml"

if [ -f evaluations/trustyai/trustyai-dsc-patch.json ]; then
  echo
  echo "==> Patching DataScienceCluster / TrustyAI when available"
  if [ "$DRY_RUN" = "false" ]; then
    oc get datasciencecluster -A >/dev/null 2>&1 && \
      oc patch datasciencecluster -A --type merge --patch-file evaluations/trustyai/trustyai-dsc-patch.json || true
  else
    echo "DRY RUN: patch DataScienceCluster with evaluations/trustyai/trustyai-dsc-patch.json"
  fi
fi

echo
echo "==> 4. Apollo GitOps applications"

apply_dir "gitops/applications"

echo
echo "==> 5. Model serving"

apply_file "bootstrap/models/llama-32-3b-instruct.yaml"

echo
echo "==> 6. MCP asset endpoints in OpenShift AI"

if [ "$DRY_RUN" = "true" ]; then
  echo "DRY RUN: create ConfigMap $ODS_NS/gen-ai-aa-mcp-servers"
else
  oc create configmap gen-ai-aa-mcp-servers \
    -n "$ODS_NS" \
    --from-literal=Apollo-Booking-MCP="{\"url\":\"http://booking-mcp.${MCP_NS}.svc.cluster.local:8080/mcp\",\"description\":\"Apollo Booking MCP server. Retrieves booking context for Apollo policy decisions.\"}" \
    --from-literal=Apollo-Disruption-MCP="{\"url\":\"http://disruption-mcp.${MCP_NS}.svc.cluster.local:8080/mcp\",\"description\":\"Apollo Disruption MCP server. Retrieves disruption and incident context.\"}" \
    --from-literal=Apollo-Policy-MCP="{\"url\":\"http://policy-mcp.${MCP_NS}.svc.cluster.local:8080/mcp\",\"description\":\"Apollo Policy MCP server. Retrieves policy candidates for emergency workflow validation.\"}" \
    --from-literal=Apollo-Case-Management-MCP="{\"url\":\"http://case-management-mcp.${MCP_NS}.svc.cluster.local:8080/mcp\",\"description\":\"Apollo Case Management MCP server. Creates or updates human-review cases.\"}" \
    --dry-run=client -o yaml | oc apply -f -
fi

echo
echo "==> 7. Pipelines"

apply_file "pipelines/apollo-agent-release-gate.yaml"

echo
echo "==> 8. Observability"

apply_file "observability/tracing/tempo-monolithic.yaml"
apply_file "observability/tracing/otel-collector.yaml"
apply_file "observability/grafana/grafana.yaml"
apply_file "observability/grafana/datasource.yaml"
apply_file "observability/grafana/dashboard.yaml"

echo
echo "==> 9. Argo CD lab RBAC"

if oc get argocd openshift-gitops -n "$GITOPS_NS" >/dev/null 2>&1; then
  if [ "$DRY_RUN" = "true" ]; then
    echo "DRY RUN: patch Argo CD RBAC defaultPolicy role:admin"
  else
    oc patch argocd openshift-gitops \
      -n "$GITOPS_NS" \
      --type merge \
      -p '{
        "spec": {
          "rbac": {
            "defaultPolicy": "role:admin",
            "scopes": "[groups]",
            "policy": "p, role:admin, applications, *, */*, allow\np, role:admin, clusters, *, *, allow\np, role:admin, repositories, *, *, allow\np, role:admin, projects, *, *, allow\np, role:admin, accounts, *, *, allow\np, role:admin, logs, get, */*, allow\np, role:admin, exec, create, */*, allow"
          }
        }
      }'
    oc rollout restart deployment/openshift-gitops-server -n "$GITOPS_NS" || true
  fi
else
  echo "WARN - Argo CD instance openshift-gitops not found."
fi

echo
echo "==> 10. API availability checks"

wait_for_crd_hint 'inferenceservice' 'KServe / InferenceService'
wait_for_crd_hint 'pipelines.*tekton' 'OpenShift Pipelines'
wait_for_crd_hint 'rollouts.*argoproj' 'Argo Rollouts'
wait_for_crd_hint 'applications.*argoproj' 'Argo CD Applications'
wait_for_crd_hint 'tempostack|opentelemetrycollector' 'Tempo / OpenTelemetry'

echo
echo "==> 11. Final inventory"

echo
echo "# Namespaces"
oc get ns | grep -E "${MODEL_NS}|${MCP_NS}|${CANARY_NS}|${OBS_NS}|${TRACING_NS}|${ODS_NS}|${GITOPS_NS}" || true

echo
echo "# Model"
oc get isvc -n "$MODEL_NS" || true

echo
echo "# MCP services"
oc get svc -n "$MCP_NS" | grep -Ei 'mcp|booking|disruption|policy|case' || true

echo
echo "# MCP asset endpoint ConfigMap"
oc get configmap gen-ai-aa-mcp-servers -n "$ODS_NS" >/dev/null 2>&1 && echo "OK - MCP asset ConfigMap exists" || echo "WARN - MCP asset ConfigMap missing"

echo
echo "# Pipelines"
oc get pipelines -n "$MCP_NS" || true
oc get tasks -n "$MCP_NS" || true

echo
echo "# Argo CD apps"
oc get applications.argoproj.io -A | grep -i apollo || true

echo
echo "# Rollouts"
oc get rollout -n "$CANARY_NS" || true
oc get analysisrun -n "$CANARY_NS" || true

echo
echo "# Routes"
oc get route -n "$CANARY_NS" || true

echo
echo "# Observability"
oc get pods -A | grep -Ei 'tempo|otel|grafana' || true

if [ "$RUN_SMOKE" = "true" ]; then
  echo
  echo "==> 12. Smoke tests"

  APOLLO_ROUTE="$(oc get route -n "$CANARY_NS" -o jsonpath='{.items[0].spec.host}' 2>/dev/null || true)"

  if [ -n "$APOLLO_ROUTE" ]; then
    echo "Apollo route: https://${APOLLO_ROUTE}"
    curl -k -sS "https://${APOLLO_ROUTE}/api/evaluations/health-emergency-regression" | head -c 1000 || true
    echo
  else
    echo "WARN - Apollo route not found."
  fi
fi

echo
echo "============================================================"
echo "Redeploy script finished"

if [ "$DRY_RUN" = "false" ]; then
  mkdir -p .local-secrets
  chmod 700 .local-secrets
  printf "%s\n" "$GRAFANA_ADMIN_PASSWORD" > .local-secrets/grafana-admin-password.txt
  chmod 600 .local-secrets/grafana-admin-password.txt

  echo "Grafana admin password was written locally to:"
  echo ".local-secrets/grafana-admin-password.txt"
  echo
  echo "This file is ignored by Git. Do not screenshot or commit it."
else
  echo "Dry run only. No Grafana password was applied."
fi

echo "============================================================"
