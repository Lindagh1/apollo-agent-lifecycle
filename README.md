# Apollo Agent Lifecycle

Apollo is a fictional travel technology provider.

This project demonstrates the complete lifecycle of a trusted AI agent on
Red Hat OpenShift AI.

## Use case

Apollo operates an AI agent that analyzes travel disruption compensation
cases for fictional airlines such as Fedora Air.

The agent retrieves booking and disruption information, selects the
applicable airline policy, recommends an action, and escalates ambiguous
cases for human review.

## Production incident

A temporary disruption policy has been introduced, but the agent continues
to select an outdated general policy. This causes incorrect approval
recommendations and missed human escalations.

## Lifecycle

- Agent development
- Model Context Protocol integration
- Evaluation and regression testing
- Runtime controls
- Red Hat OpenShift Pipelines
- Red Hat OpenShift GitOps
- Prometheus and Grafana observability
- Canary deployment and rollback