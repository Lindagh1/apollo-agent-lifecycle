#!/usr/bin/env bash
set -euo pipefail

DEV_NS="${DEV_NS:-apollo-dev}"
CANARY_NS="${CANARY_NS:-apollo-canary}"
DEV_DEPLOY="${DEV_DEPLOY:-apollo-console}"
ROLLOUT="${ROLLOUT:-apollo-console-rollout}"
BUILD_NAME="${BUILD_NAME:-apollo-console}"

echo "============================================================"
echo "Apply Apollo canary runtime configuration"
echo "============================================================"

echo
echo "==> 1. Apply canary RBAC and promotion pipeline"

oc apply -f applications/apollo-console/manifests/canary-traffic-rbac.yaml
oc apply -f pipelines/apollo-canary-promotion.yaml

echo
echo "==> 2. Ensure Apollo Console pods can read the Kubernetes service account token"

if oc get deployment "$DEV_DEPLOY" -n "$DEV_NS" >/dev/null 2>&1; then
  oc patch deployment "$DEV_DEPLOY" \
    -n "$DEV_NS" \
    --type=merge \
    -p '{"spec":{"template":{"spec":{"automountServiceAccountToken":true}}}}'
fi

if oc get rollouts.argoproj.io "$ROLLOUT" -n "$CANARY_NS" >/dev/null 2>&1; then
  oc patch rollouts.argoproj.io "$ROLLOUT" \
    -n "$CANARY_NS" \
    --type=merge \
    -p '{"spec":{"template":{"spec":{"automountServiceAccountToken":true}}}}'
fi

echo
echo "==> 3. Rebuild Apollo Console image when BuildConfig exists"

if oc get bc "$BUILD_NAME" -n "$DEV_NS" >/dev/null 2>&1; then
  oc start-build "$BUILD_NAME" \
    -n "$DEV_NS" \
    --from-dir=applications/apollo-console \
    --follow

  PULLSPEC="$(oc get istag "${BUILD_NAME}:latest" -n "$DEV_NS" -o jsonpath='{.image.dockerImageReference}')"

  if [ -n "$PULLSPEC" ]; then
    echo "Built image: $PULLSPEC"

    if oc get deployment "$DEV_DEPLOY" -n "$DEV_NS" >/dev/null 2>&1; then
      DEV_CONTAINER="$(oc get deploy "$DEV_DEPLOY" -n "$DEV_NS" -o jsonpath='{.spec.template.spec.containers[0].name}')"

      oc set image deployment/"$DEV_DEPLOY" \
        -n "$DEV_NS" \
        "$DEV_CONTAINER=$PULLSPEC"

      oc rollout status deployment/"$DEV_DEPLOY" -n "$DEV_NS" --timeout=180s || true
    fi

    if oc get rollouts.argoproj.io "$ROLLOUT" -n "$CANARY_NS" >/dev/null 2>&1; then
      oc patch rollouts.argoproj.io "$ROLLOUT" \
        -n "$CANARY_NS" \
        --type=json \
        -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/image\",\"value\":\"$PULLSPEC\"}]" || true

      oc patch rollouts.argoproj.io "$ROLLOUT" \
        -n "$CANARY_NS" \
        --type=merge \
        -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"apollo.redhat.com/runtime-applied-at\":\"$(date +%s)\"}}}}}" || true
    fi
  fi
else
  echo "WARN: BuildConfig $DEV_NS/$BUILD_NAME not found. Skipping image rebuild."
fi

echo
echo "==> 4. Verify live canary API"

if oc get route apollo-console-canary -n "$CANARY_NS" >/dev/null 2>&1; then
  APOLLO_HOST="$(oc get route apollo-console-canary -n "$CANARY_NS" -o jsonpath='{.spec.host}')"

  curl -sk "https://${APOLLO_HOST}/api/release/canary-traffic" | jq . || true
fi

echo
echo "DONE"
