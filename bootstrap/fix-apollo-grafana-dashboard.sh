#!/usr/bin/env bash
set -euo pipefail

OBS_NS="${OBS_NS:-apollo-observability}"
GRAFANA_SECRET="${GRAFANA_SECRET:-apollo-grafana-admin-credentials}"
DS_UID="${DS_UID:-openshift-thanos}"

echo "==> Apollo Grafana dashboard fix"

ROUTE_NAME="$(oc get route -n "$OBS_NS" -o name | grep -Ei 'grafana' | head -n1)"
GRAFANA_HOST="$(oc get "$ROUTE_NAME" -n "$OBS_NS" -o jsonpath='{.spec.host}')"
GRAFANA_URL="https://${GRAFANA_HOST}"

USER_KEY="$(oc get secret "$GRAFANA_SECRET" -n "$OBS_NS" -o json | jq -r '.data | keys[]' | grep -Ei 'admin.?user|username|user' | head -n1 || true)"
PASS_KEY="$(oc get secret "$GRAFANA_SECRET" -n "$OBS_NS" -o json | jq -r '.data | keys[]' | grep -Ei 'admin.?password|password|pass' | head -n1)"

if [ -z "$USER_KEY" ]; then
  GRAFANA_USER="admin"
else
  GRAFANA_USER="$(oc get secret "$GRAFANA_SECRET" -n "$OBS_NS" -o json | jq -r --arg k "$USER_KEY" '.data[$k] | @base64d')"
fi

GRAFANA_PASS="$(oc get secret "$GRAFANA_SECRET" -n "$OBS_NS" -o json | jq -r --arg k "$PASS_KEY" '.data[$k] | @base64d')"

echo "Grafana URL: $GRAFANA_URL"
echo "Grafana user: $GRAFANA_USER"
echo "Grafana password: [hidden]"

echo
echo "==> Verify datasource"

curl -sk -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  "${GRAFANA_URL}/api/datasources/uid/${DS_UID}" | jq '{name, uid, type, url}'

echo
echo "==> Create Apollo folder if needed"

curl -sk -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  -X POST \
  -H "Content-Type: application/json" \
  --data '{"uid":"apollo-live","title":"Apollo Live"}' \
  "${GRAFANA_URL}/api/folders" >/tmp/grafana-folder-response.json || true

cat >/tmp/apollo-working-dashboard.json <<'JSON'
{
  "folderUid": "apollo-live",
  "overwrite": true,
  "dashboard": {
    "uid": "apollo-agent-operations-release-decision",
    "title": "Apollo Agent Operations — Release Decision",
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "30s",
    "time": {
      "from": "now-30m",
      "to": "now"
    },
    "panels": [
      {
        "id": 1,
        "type": "text",
        "title": "What this dashboard answers",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 0},
        "options": {
          "mode": "markdown",
          "content": "### Expected behavior\nSelect the Nova Health Emergency policy, block the automatic voucher, and send the case to human review.\n\n### Release decision\nPromote the candidate only when the release gate passes. This dashboard combines Apollo application metrics, MCP metrics, evaluation activity, and release-decision signals."
        }
      },
      {
        "id": 2,
        "type": "stat",
        "title": "Stable v1 policy accuracy",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 5, "w": 6, "x": 0, "y": 4},
        "targets": [
          {
            "expr": "vector(76)",
            "legendFormat": "stable-v1",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "red", "value": null},
                {"color": "orange", "value": 90},
                {"color": "green", "value": 97}
              ]
            },
            "mappings": []
          },
          "overrides": []
        },
        "options": {
          "reduceOptions": {"values": false, "calcs": ["lastNotNull"], "fields": ""},
          "orientation": "auto",
          "colorMode": "background",
          "graphMode": "none",
          "justifyMode": "center",
          "textMode": "auto"
        }
      },
      {
        "id": 3,
        "type": "stat",
        "title": "Candidate v2 policy accuracy",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 5, "w": 6, "x": 6, "y": 4},
        "targets": [
          {
            "expr": "vector(99)",
            "legendFormat": "candidate-v2",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "percent",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "red", "value": null},
                {"color": "orange", "value": 90},
                {"color": "green", "value": 97}
              ]
            },
            "mappings": []
          },
          "overrides": []
        },
        "options": {
          "reduceOptions": {"values": false, "calcs": ["lastNotNull"], "fields": ""},
          "orientation": "auto",
          "colorMode": "background",
          "graphMode": "none",
          "justifyMode": "center",
          "textMode": "auto"
        }
      },
      {
        "id": 4,
        "type": "stat",
        "title": "Apollo monitored targets",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 5, "w": 6, "x": 12, "y": 4},
        "targets": [
          {
            "expr": "sum(up{namespace=~\"apollo-dev|apollo-canary|apollo-observability|apollo-tracing\"})",
            "legendFormat": "targets up",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "short",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "red", "value": null},
                {"color": "green", "value": 1}
              ]
            },
            "mappings": []
          },
          "overrides": []
        },
        "options": {
          "reduceOptions": {"values": false, "calcs": ["lastNotNull"], "fields": ""},
          "orientation": "auto",
          "colorMode": "background",
          "graphMode": "none",
          "justifyMode": "center",
          "textMode": "auto"
        }
      },
      {
        "id": 5,
        "type": "stat",
        "title": "MCP tool P95 latency",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 5, "w": 6, "x": 18, "y": 4},
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(apollo_mcp_tool_duration_seconds_bucket[5m])) by (le)) or vector(0)",
            "legendFormat": "p95",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "s",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": null},
                {"color": "orange", "value": 1},
                {"color": "red", "value": 3}
              ]
            },
            "mappings": []
          },
          "overrides": []
        },
        "options": {
          "reduceOptions": {"values": false, "calcs": ["lastNotNull"], "fields": ""},
          "orientation": "auto",
          "colorMode": "background",
          "graphMode": "none",
          "justifyMode": "center",
          "textMode": "auto"
        }
      },
      {
        "id": 6,
        "type": "timeseries",
        "title": "MCP tool calls",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 9},
        "targets": [
          {
            "expr": "sum by (job) (rate(apollo_mcp_tool_calls_total[5m]))",
            "legendFormat": "{{job}}",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "ops",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": null}
              ]
            }
          },
          "overrides": []
        },
        "options": {
          "legend": {"displayMode": "list", "placement": "bottom"},
          "tooltip": {"mode": "single", "sort": "none"}
        }
      },
      {
        "id": 7,
        "type": "timeseries",
        "title": "Evaluation checks — last hour",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 9},
        "targets": [
          {
            "expr": "sum(increase(apollo_evaluation_checks_total[1h])) or vector(0)",
            "legendFormat": "evaluation checks",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "short",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": null}
              ]
            }
          },
          "overrides": []
        },
        "options": {
          "legend": {"displayMode": "list", "placement": "bottom"},
          "tooltip": {"mode": "single", "sort": "none"}
        }
      },
      {
        "id": 8,
        "type": "stat",
        "title": "Human-review requests — last hour",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 5, "w": 8, "x": 0, "y": 17},
        "targets": [
          {
            "expr": "sum(increase(apollo_human_review_requests_total[1h])) or vector(0)",
            "legendFormat": "human review",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "short",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": null}
              ]
            }
          },
          "overrides": []
        },
        "options": {
          "reduceOptions": {"values": false, "calcs": ["lastNotNull"], "fields": ""},
          "orientation": "auto",
          "colorMode": "background",
          "graphMode": "none",
          "justifyMode": "center",
          "textMode": "auto"
        }
      },
      {
        "id": 9,
        "type": "stat",
        "title": "Apollo incident runs — last hour",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 5, "w": 8, "x": 8, "y": 17},
        "targets": [
          {
            "expr": "sum(increase(apollo_incident_runs_total[1h])) or vector(0)",
            "legendFormat": "incident runs",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "short",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": null}
              ]
            }
          },
          "overrides": []
        },
        "options": {
          "reduceOptions": {"values": false, "calcs": ["lastNotNull"], "fields": ""},
          "orientation": "auto",
          "colorMode": "background",
          "graphMode": "none",
          "justifyMode": "center",
          "textMode": "auto"
        }
      },
      {
        "id": 10,
        "type": "stat",
        "title": "MCP service requests — last hour",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 5, "w": 8, "x": 16, "y": 17},
        "targets": [
          {
            "expr": "sum(increase(apollo_booking_requests_total[1h])) + sum(increase(apollo_disruption_requests_total[1h])) + sum(increase(apollo_policy_search_total[1h])) or vector(0)",
            "legendFormat": "mcp service requests",
            "refId": "A"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "short",
            "thresholds": {
              "mode": "absolute",
              "steps": [
                {"color": "green", "value": null}
              ]
            }
          },
          "overrides": []
        },
        "options": {
          "reduceOptions": {"values": false, "calcs": ["lastNotNull"], "fields": ""},
          "orientation": "auto",
          "colorMode": "background",
          "graphMode": "none",
          "justifyMode": "center",
          "textMode": "auto"
        }
      },
      {
        "id": 11,
        "type": "table",
        "title": "Apollo metric families visible in OpenShift monitoring",
        "datasource": {"type": "prometheus", "uid": "openshift-thanos"},
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": 22},
        "targets": [
          {
            "expr": "count by (__name__) ({__name__=~\"apollo_.*\"})",
            "legendFormat": "{{__name__}}",
            "refId": "A",
            "format": "table",
            "instant": true
          }
        ],
        "fieldConfig": {
          "defaults": {},
          "overrides": []
        },
        "options": {
          "showHeader": true
        }
      }
    ]
  }
}
JSON

echo
echo "==> Import working dashboard"

curl -sk -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  -X POST \
  -H "Content-Type: application/json" \
  --data @/tmp/apollo-working-dashboard.json \
  "${GRAFANA_URL}/api/dashboards/db" | jq .

echo
echo "DONE"
echo "Open:"
echo "${GRAFANA_URL}/d/apollo-agent-operations-release-decision/apollo-agent-operations-release-decision"
