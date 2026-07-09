#!/usr/bin/env bash
set -euo pipefail

CANARY_NS="${CANARY_NS:-apollo-canary}"
ROLLOUT="${ROLLOUT:-apollo-console-rollout}"
ROUTE="${ROUTE:-apollo-console-canary}"

echo "============================================================"
echo "Reset Apollo canary lab"
echo "============================================================"

STAMP="$(date +%s)"

echo
echo "==> 1. Trigger a fresh canary rollout using a harmless annotation"

oc patch rollouts.argoproj.io "$ROLLOUT" \
  -n "$CANARY_NS" \
  --type=merge \
  -p "{
    \"spec\": {
      \"template\": {
        \"metadata\": {
          \"annotations\": {
            \"apollo.redhat.com/lab-reset\": \"${STAMP}\",
            \"apollo.redhat.com/runtime-release\": \"candidate-v2\"
          }
        }
      }
    }
  }"

echo
echo "==> 2. Wait until rollout reaches the first canary pause"

for i in $(seq 1 90); do
  PHASE="$(oc get rollouts.argoproj.io "$ROLLOUT" -n "$CANARY_NS" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  STEP="$(oc get rollouts.argoproj.io "$ROLLOUT" -n "$CANARY_NS" -o jsonpath='{.status.currentStepIndex}' 2>/dev/null || true)"
  PAUSED="$(oc get rollouts.argoproj.io "$ROLLOUT" -n "$CANARY_NS" -o jsonpath='{.status.controllerPause}' 2>/dev/null || true)"
  STABLE="$(oc get route "$ROUTE" -n "$CANARY_NS" -o jsonpath='{.spec.to.weight}' 2>/dev/null || true)"
  CANDIDATE="$(oc get route "$ROUTE" -n "$CANARY_NS" -o jsonpath='{.spec.alternateBackends[0].weight}' 2>/dev/null || true)"

  echo "phase=${PHASE:-unknown} step=${STEP:-unknown} paused=${PAUSED:-unknown} stable=${STABLE:-unknown} candidate=${CANDIDATE:-unknown}"

  if [ "$CANDIDATE" = "10" ] && [ "$PAUSED" = "true" ]; then
    echo
    echo "PASS: lab reset to 90/10 paused state."
    break
  fi

  sleep 5
done

echo
echo "==> 3. Final state"

oc get rollouts.argoproj.io "$ROLLOUT" -n "$CANARY_NS" -o json | jq '{
  phase: .status.phase,
  currentStepIndex: .status.currentStepIndex,
  controllerPause: .status.controllerPause,
  pauseConditions: .status.pauseConditions,
  canaryWeights: .status.canary.weights
}'

oc get route "$ROUTE" -n "$CANARY_NS" \
  -o jsonpath='{.spec.to.name}{"="}{.spec.to.weight}{"\n"}{range .spec.alternateBackends[*]}{.name}{"="}{.weight}{"\n"}{end}'

APOLLO_HOST="$(oc get route "$ROUTE" -n "$CANARY_NS" -o jsonpath='{.spec.host}')"

echo
echo "Apollo live traffic API:"
curl -sk "https://${APOLLO_HOST}/api/release/canary-traffic" | jq .
