#!/usr/bin/env bash
set -euo pipefail

CANARY_NS="${CANARY_NS:-apollo-canary}"
ROLLOUT="${ROLLOUT:-apollo-console-rollout}"
ROUTE="${ROUTE:-apollo-console-canary}"

echo "============================================================"
echo "Normalize Apollo canary route"
echo "============================================================"

PHASE="$(oc get rollouts.argoproj.io "$ROLLOUT" -n "$CANARY_NS" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
STABLE="$(oc get route "$ROUTE" -n "$CANARY_NS" -o jsonpath='{.spec.to.weight}' 2>/dev/null || true)"
CANDIDATE="$(oc get route "$ROUTE" -n "$CANARY_NS" -o jsonpath='{.spec.alternateBackends[0].weight}' 2>/dev/null || true)"

echo "phase=$PHASE"
echo "stable=$STABLE"
echo "candidate=$CANDIDATE"

if [ "$PHASE" = "Healthy" ] && [ "$STABLE" = "100" ] && [ "$CANDIDATE" = "100" ]; then
  echo
  echo "Detected stale 100/100 route after full promotion. Normalizing to stable=100 candidate=0."

  oc patch route "$ROUTE" -n "$CANARY_NS" --type=merge -p '{
    "spec": {
      "to": {
        "kind": "Service",
        "name": "apollo-console-stable",
        "weight": 100
      },
      "alternateBackends": [
        {
          "kind": "Service",
          "name": "apollo-console-candidate",
          "weight": 0
        }
      ]
    }
  }'
else
  echo "No normalization needed."
fi

echo
echo "Final route:"
oc get route "$ROUTE" -n "$CANARY_NS" \
  -o jsonpath='{.spec.to.name}{"="}{.spec.to.weight}{"\n"}{range .spec.alternateBackends[*]}{.name}{"="}{.weight}{"\n"}{end}'
