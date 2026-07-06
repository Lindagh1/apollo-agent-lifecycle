# Apollo evaluations

The current regression suite validates the deployed Apollo workflow for
`APOLLO-001` against the Nova Health Emergency policy override.

The live evaluation checks:

- booking retrieval;
- disruption retrieval;
- candidate policy selection;
- schema-constrained model output;
- deterministic validation;
- human-review creation;
- automatic-action blocking;
- review-queue assignment.

Run it against the OpenShift Route:

```bash
APOLLO_CONSOLE_URL="https://<apollo-console-route>" \
  python evaluations/run_health_emergency.py
```

The process exits with code `0` when the candidate passes and `1` when a
release gate fails, so the same runner can later be used in OpenShift
Pipelines.
