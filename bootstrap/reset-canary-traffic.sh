#!/usr/bin/env bash
set -euo pipefail

CANARY_NS="${CANARY_NS:-apollo-canary}"
ROUTE_NAME="${ROUTE_NAME:-apollo-console-canary}"

echo "Reset Apollo canary traffic"
echo "Route: $CANARY_NS/$ROUTE_NAME"
echo "stable=100 candidate=0"

oc -n "$CANARY_NS" patch route "$ROUTE_NAME" --type=merge -p '{
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

oc -n "$CANARY_NS" get route "$ROUTE_NAME" \
  -o jsonpath='{.spec.to.name}{"="}{.spec.to.weight}{"\n"}{range .spec.alternateBackends[*]}{.name}{"="}{.weight}{"\n"}{end}'
