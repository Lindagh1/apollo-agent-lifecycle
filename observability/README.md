# Apollo observability

This directory contains OpenShift user-workload monitoring resources and an
importable Grafana dashboard for the Apollo agent lifecycle lab.

## Metrics endpoint

The Apollo console exposes Prometheus metrics at `/metrics`. The MCP services
also expose `/metrics`.

## OpenShift resources

- `servicemonitors/apollo-services.yaml`: discovers the console and MCP services.
- `prometheus-rules/apollo-agent-rules.yaml`: release-gate and runtime alerts.
- `grafana-dashboards/apollo-agent-operations.json`: Grafana dashboard JSON.

User-workload monitoring must be enabled by a cluster administrator for the
ServiceMonitor and PrometheusRule resources to be evaluated.
