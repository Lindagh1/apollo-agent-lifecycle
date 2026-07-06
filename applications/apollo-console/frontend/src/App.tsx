import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
  version: string;
};

type ExecutionStatus =
  | "healthy"
  | "failed"
  | "blocked"
  | "not-connected";

type ExecutionStep = {
  component: string;
  status: ExecutionStatus;
  tool?: string;
  detail?: string;
  durationMs?: number | null;
};

type Policy = {
  policyId: string;
  airline: string;
  priority: number;
  name: string;
  disruptionType: string;
  eventId: string | null;
  effectiveFrom: string;
  effectiveTo: string;
  recommendedAction: string;
  humanReviewRequired: boolean;
  explanation: string;
  sourceFile: string;
};

type ProductionDecision = {
  release: string;
  source: string;
  selectedPolicyId: string | null;
  recommendation: string | null;
  humanReviewRequired: boolean;
  passed: boolean;
};

type CandidateDecision = {
  release: string;
  model: string;
  selectedPolicyId: string | null;
  recommendation: string | null;
  humanReviewRequired: boolean | null;
  explanation: string | null;
  passed: boolean;
  error: string | null;
};

type ValidationResult = {
  status: "passed" | "blocked";
  finalPolicyId: string | null;
  finalAction: string;
  humanReviewRequired: boolean;
  automaticActionAllowed: boolean;
  reasons: string[];
  summary: string;
};

type HumanReviewCase = {
  caseId: string;
  policyId?: string;
  recommendation?: string;
  reason?: string;
  queue?: string;
  status: string;
  automaticActionBlocked: boolean;
  reviewer?: string | null;
  reviewerDecision?: string | null;
  reviewerNotes?: string | null;
  createdAt?: string;
  updatedAt?: string;
};

type HumanReview = {
  connected: boolean;
  result: string;
  error: string | null;
  case: HumanReviewCase | null;
};

type IncidentResponse = {
  caseId: string;
  airline: string;
  scenario: string;
  travelDate: string;
  expectedPolicyId: string;
  expectedAction: string;
  selectedPolicyId: string | null;
  actualAction: string | null;
  passed: boolean;
  modelConnected: boolean;
  productionDecision: ProductionDecision;
  candidateDecision: CandidateDecision;
  validation: ValidationResult;
  humanReview: HumanReview;
  execution: ExecutionStep[];
  policies: Policy[];
};

const metrics = [
  {
    label: "Agent status",
    value: "Degraded",
    detail: "Stable release below target",
    warning: true
  },
  {
    label: "Policy selection accuracy",
    value: "76%",
    detail: "Target: 97%"
  },
  {
    label: "Human escalation accuracy",
    value: "71%",
    detail: "Target: 95%"
  },
  {
    label: "Incorrect automated decisions",
    value: "8%",
    detail: "Target: 0%",
    warning: true
  },
  {
    label: "P95 latency",
    value: "2.1 s",
    detail: "Within target"
  }
];

function humanize(value: string | null | undefined) {
  if (!value) {
    return "Not available";
  }

  return value.replace(/-/g, " ");
}

function App() {
  const [apiStatus, setApiStatus] = useState("Checking");
  const [incident, setIncident] =
    useState<IncidentResponse | null>(null);
  const [incidentError, setIncidentError] =
    useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Health request failed");
        }

        return response.json();
      })
      .then((health: HealthResponse) => {
        setApiStatus(
          `${health.status} · v${health.version}`
        );
      })
      .catch(() => {
        setApiStatus("Unavailable");
      });

    fetch("/api/incidents/APOLLO-001")
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Incident request failed: ${response.status}`
          );
        }

        return response.json();
      })
      .then((payload: IncidentResponse) => {
        setIncident(payload);
      })
      .catch((error: Error) => {
        setIncidentError(error.message);
      });
  }, []);

  return (
    <div className="application">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">●</span>
          Apollo
        </div>

        <nav>
          <a className="active" href="#overview">
            Overview
          </a>
          <a href="#executions">Executions</a>
          <a href="#evaluations">Evaluations</a>
          <a href="#releases">Releases</a>
          <a href="#settings">Settings</a>
        </nav>

        <div className="sidebar-status">
          API status
          <strong>{apiStatus}</strong>
        </div>
      </aside>

      <main>
        <header>
          <div>
            <h1>Apollo Operations Console</h1>
            <p>Agent health and release visibility</p>
          </div>

          <span className="environment">apollo-dev</span>
        </header>

        <section className="metrics" id="overview">
          {metrics.map((metric) => (
            <article className="metric-card" key={metric.label}>
              <span>{metric.label}</span>

              <strong
                className={
                  metric.warning ? "warning-text" : ""
                }
              >
                {metric.value}
              </strong>

              <small>{metric.detail}</small>
            </article>
          ))}
        </section>

        <section className="alert">
          <span className="alert-icon">!</span>

          <div>
            <strong>
              Platform healthy — stable agent quality degraded
            </strong>

            <p>
              MCP services and the model endpoint are available.
              The stable release still ranks the general policy
              before the emergency override.
            </p>
          </div>
        </section>

        {incidentError && (
          <section className="panel error-panel">
            Unable to load the production incident:{" "}
            {incidentError}
          </section>
        )}

        {!incident && !incidentError && (
          <section className="panel">
            Running the incident through MCP services and the
            OpenShift AI model...
          </section>
        )}

        {incident && (
          <div className="content-grid">
            <section className="panel incident-panel">
              <div className="section-heading">
                <div>
                  <h2>Recent incident</h2>
                  <p>
                    Stable production behavior compared with the
                    schema-constrained candidate.
                  </p>
                </div>

                <span className="status-badge degraded">
                  Stable degraded
                </span>
              </div>

              <div className="incident-summary">
                <div>
                  <span>Case ID</span>
                  <strong>{incident.caseId}</strong>
                </div>

                <div>
                  <span>Airline</span>
                  <strong>{incident.airline}</strong>
                </div>

                <div>
                  <span>Scenario</span>
                  <strong>{incident.scenario}</strong>
                </div>

                <div>
                  <span>Expected action</span>
                  <strong>{humanize(incident.expectedAction)}</strong>
                </div>

                <div>
                  <span>Stable action</span>
                  <strong className="danger-text">
                    {humanize(incident.actualAction)}
                  </strong>
                </div>
              </div>

              <h3 id="executions">Execution path</h3>

              <div className="execution-flow">
                {incident.execution.map((step, index) => (
                  <div
                    className="flow-entry"
                    key={step.component}
                  >
                    <div
                      className={`flow-step ${step.status}`}
                    >
                      <strong>
                        {humanize(step.component)}
                      </strong>

                      {step.detail && (
                        <small>{step.detail}</small>
                      )}

                      {typeof step.durationMs === "number" && (
                        <span className="latency">
                          {Math.round(step.durationMs)} ms
                        </span>
                      )}
                    </div>

                    {index <
                      incident.execution.length - 1 && (
                      <span className="flow-arrow">→</span>
                    )}
                  </div>
                ))}
              </div>

              <h3>Policies returned by policy-mcp</h3>

              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Policy ID</th>
                      <th>Priority</th>
                      <th>Action</th>
                      <th>Stable v1</th>
                      <th>Candidate v2</th>
                      <th>Expected</th>
                    </tr>
                  </thead>

                  <tbody>
                    {incident.policies.map((policy) => (
                      <tr key={policy.policyId}>
                        <td>{policy.policyId}</td>
                        <td>{policy.priority}</td>
                        <td>
                          {humanize(policy.recommendedAction)}
                        </td>
                        <td>
                          {policy.policyId ===
                          incident.productionDecision.selectedPolicyId
                            ? "Selected"
                            : "—"}
                        </td>
                        <td>
                          {policy.policyId ===
                          incident.candidateDecision.selectedPolicyId
                            ? "Selected"
                            : "—"}
                        </td>
                        <td>
                          {policy.policyId ===
                          incident.expectedPolicyId
                            ? "Required"
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="decision-grid" id="evaluations">
                <article className="decision-card production">
                  <div className="decision-card-header">
                    <span>Stable v1</span>
                    <span className="status-badge failed">
                      Failed
                    </span>
                  </div>

                  <strong>
                    {incident.productionDecision.selectedPolicyId}
                  </strong>
                  <p>
                    Recommendation:{" "}
                    {humanize(
                      incident.productionDecision.recommendation
                    )}
                  </p>
                  <small>
                    Source: {incident.productionDecision.source}
                  </small>
                </article>

                <article className="decision-card candidate">
                  <div className="decision-card-header">
                    <span>Candidate v2</span>
                    <span
                      className={`status-badge ${
                        incident.candidateDecision.passed
                          ? "passed"
                          : "failed"
                      }`}
                    >
                      {incident.candidateDecision.passed
                        ? "Passed"
                        : "Failed"}
                    </span>
                  </div>

                  <strong>
                    {incident.candidateDecision.selectedPolicyId ??
                      "No model decision"}
                  </strong>
                  <p>
                    Recommendation:{" "}
                    {humanize(
                      incident.candidateDecision.recommendation
                    )}
                  </p>
                  <small>
                    Model: {incident.candidateDecision.model}
                  </small>

                  {incident.candidateDecision.explanation && (
                    <blockquote>
                      {incident.candidateDecision.explanation}
                    </blockquote>
                  )}

                  {incident.candidateDecision.error && (
                    <p className="danger-text">
                      {incident.candidateDecision.error}
                    </p>
                  )}
                </article>

                <article
                  className={`decision-card validation ${
                    incident.validation.status
                  }`}
                >
                  <div className="decision-card-header">
                    <span>Deterministic validation</span>
                    <span
                      className={`status-badge ${
                        incident.validation.status === "passed"
                          ? "passed"
                          : "blocked"
                      }`}
                    >
                      {incident.validation.status === "passed"
                        ? "Accepted"
                        : "Blocked"}
                    </span>
                  </div>

                  <strong>
                    Final action:{" "}
                    {humanize(incident.validation.finalAction)}
                  </strong>
                  <p>{incident.validation.summary}</p>
                  <small>
                    Automatic action:{" "}
                    {incident.validation.automaticActionAllowed
                      ? "allowed"
                      : "blocked"}
                  </small>

                  {incident.validation.reasons.length > 0 && (
                    <ul>
                      {incident.validation.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  )}
                </article>

                <article className="decision-card human-review">
                  <div className="decision-card-header">
                    <span>Human-in-the-loop</span>
                    <span
                      className={`status-badge ${
                        incident.humanReview.case?.status ===
                        "pending-human-review"
                          ? "pending"
                          : incident.humanReview.error
                          ? "failed"
                          : "passed"
                      }`}
                    >
                      {incident.humanReview.case?.status ===
                      "pending-human-review"
                        ? "Pending"
                        : incident.humanReview.error
                        ? "Failed"
                        : humanize(
                            incident.humanReview.case?.status ??
                              incident.humanReview.result
                          )}
                    </span>
                  </div>

                  <strong>
                    Queue: {incident.humanReview.case?.queue ?? "Not assigned"}
                  </strong>

                  <p>
                    Policy: {incident.humanReview.case?.policyId ?? "Not available"}
                  </p>

                  <small>
                    Automatic action: {incident.humanReview.case?.automaticActionBlocked
                      ? "blocked"
                      : "not blocked"}
                  </small>

                  {incident.humanReview.case?.reason && (
                    <blockquote>
                      {incident.humanReview.case.reason}
                    </blockquote>
                  )}

                  {incident.humanReview.error && (
                    <p className="danger-text">
                      {incident.humanReview.error}
                    </p>
                  )}
                </article>
              </div>
            </section>

            <aside className="panel release-panel" id="releases">
              <h2>Release comparison</h2>

              <div className="release stable">
                <span>Stable v1</span>
                <strong>76%</strong>
                <small>Policy accuracy</small>
              </div>

              <div className="versus">VS</div>

              <div className="release candidate">
                <span>Candidate v2</span>
                <strong>99%</strong>
                <small>Policy accuracy</small>
              </div>

              <div className="release-gate">
                <span>Current case gate</span>
                <strong
                  className={
                    incident.candidateDecision.passed
                      ? "success-text"
                      : "danger-text"
                  }
                >
                  {incident.candidateDecision.passed
                    ? "PASS"
                    : "FAIL"}
                </strong>
                <small>
                  {incident.validation.humanReviewRequired
                    ? "Human review enforced"
                    : "Automatic processing allowed"}
                </small>
              </div>

              <label>Canary traffic</label>
              <progress value="10" max="100" />
              <strong>10%</strong>

              <button className="primary-button" disabled>
                Promote
              </button>

              <button className="secondary-button" disabled>
                Rollback
              </button>

              <small className="muted-note">
                Release actions will be connected through
                OpenShift GitOps later in the lab.
              </small>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
