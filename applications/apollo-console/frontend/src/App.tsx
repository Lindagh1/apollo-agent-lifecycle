import { useCallback, useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
  version: string;
  release: string;
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

type EvaluationCheck = {
  id: string;
  name: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
};

type ReleaseGate = {
  name: string;
  stable: boolean;
  candidate: boolean;
};

type EvaluationRun = {
  runId: string;
  suite: string;
  description: string;
  generatedAt: string;
  status: "passed" | "failed";
  model: string;
  caseCount: number;
  checkCount: number;
  passedChecks: number;
  failedChecks: number;
  totalLatencyMs: number;
  stable: {
    release: string;
    status: "passed" | "failed";
    selectedPolicyId: string | null;
    recommendation: string | null;
  };
  candidate: {
    release: string;
    status: "passed" | "failed";
    selectedPolicyId: string | null;
    recommendation: string | null;
  };
  releaseGates: ReleaseGate[];
  cases: Array<{
    caseId: string;
    scenario: string;
    status: "passed" | "failed";
    checks: EvaluationCheck[];
  }>;
};

type ViewName = "overview" | "evaluations";

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

function displayValue(value: unknown) {
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }

  if (value === null || value === undefined) {
    return "Not available";
  }

  return String(value);
}

function App() {
  const [canaryTraffic, setCanaryTraffic] = useState<any>(null);

  useEffect(() => {
    const loadCanaryTraffic = async () => {
      try {
        const response = await fetch("/api/release/canary-traffic");
        const data = await response.json();
        setCanaryTraffic(data);
      } catch (error) {
        setCanaryTraffic({ error: String(error) });
      }
    };

    loadCanaryTraffic();
    const interval = window.setInterval(loadCanaryTraffic, 10000);
    return () => window.clearInterval(interval);
  }, []);

  const canaryCandidateWeight =
    canaryTraffic && canaryTraffic.candidate_weight !== null && canaryTraffic.candidate_weight !== undefined
      ? `${canaryTraffic.candidate_weight}%`
      : "unknown";

  const canaryStableWeight =
    canaryTraffic && canaryTraffic.stable_weight !== null && canaryTraffic.stable_weight !== undefined
      ? `${canaryTraffic.stable_weight}%`
      : "unknown";

  const [apiStatus, setApiStatus] = useState("Checking");
  const [view, setView] = useState<ViewName>(() =>
    window.location.hash === "#evaluations"
      ? "evaluations"
      : "overview"
  );
  const [incident, setIncident] =
    useState<IncidentResponse | null>(null);
  const [incidentError, setIncidentError] =
    useState<string | null>(null);
  const [evaluation, setEvaluation] =
    useState<EvaluationRun | null>(null);
  const [evaluationLoading, setEvaluationLoading] =
    useState(false);
  const [evaluationError, setEvaluationError] =
    useState<string | null>(null);

  const loadEvaluation = useCallback(() => {
    setEvaluationLoading(true);
    setEvaluationError(null);

    fetch("/api/evaluations/health-emergency-regression")
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Evaluation request failed: ${response.status}`
          );
        }

        return response.json();
      })
      .then((payload: EvaluationRun) => {
        setEvaluation(payload);
      })
      .catch((error: Error) => {
        setEvaluationError(error.message);
      })
      .finally(() => {
        setEvaluationLoading(false);
      });
  }, []);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Health request failed");
        }

        return response.json();
      })
      .then((health: HealthResponse) => {
        setApiStatus(`${health.status} · v${health.version}`);
      })
      .catch(() => {
        setApiStatus("Unavailable");
      });

    fetch("/api/incidents/APOLLO-001/comparison")
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

  useEffect(() => {
    const handleHashChange = () => {
      setView(
        window.location.hash === "#evaluations"
          ? "evaluations"
          : "overview"
      );
    };

    window.addEventListener("hashchange", handleHashChange);

    return () => {
      window.removeEventListener("hashchange", handleHashChange);
    };
  }, []);

  useEffect(() => {
    if (view === "evaluations" && !evaluation) {
      loadEvaluation();
    }
  }, [evaluation, loadEvaluation, view]);

  return (
    <div className="application">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">●</span>
          Apollo
        </div>

        <nav>
          <a
            className={view === "overview" ? "active" : ""}
            href="#overview"
            onClick={() => setView("overview")}
          >
            Overview
          </a>
          <a href="#overview" onClick={() => setView("overview")}>
            Executions
          </a>
          <a
            className={view === "evaluations" ? "active" : ""}
            href="#evaluations"
            onClick={() => setView("evaluations")}
          >
            Evaluations
          </a>
          <a href="#overview" onClick={() => setView("overview")}>
            Releases
          </a>
          <a href="#overview" onClick={() => setView("overview")}>
            Settings
          </a>
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

        {view === "overview" && (
          <>
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
                Unable to load the production incident: {incidentError}
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

                  <h3>Execution path</h3>
                  <div className="execution-flow">
                    {incident.execution.map((step, index) => (
                      <div className="flow-entry" key={step.component}>
                        <div className={`flow-step ${step.status}`}>
                          <strong>{humanize(step.component)}</strong>
                          {step.detail && <small>{step.detail}</small>}
                          {typeof step.durationMs === "number" && (
                            <span className="latency">
                              {Math.round(step.durationMs)} ms
                            </span>
                          )}
                        </div>
                        {index < incident.execution.length - 1 && (
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
                            <td>{humanize(policy.recommendedAction)}</td>
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

                  <div className="decision-grid">
                    <article className="decision-card production">
                      <div className="decision-card-header">
                        <span>Stable v1</span>
                        <span className="status-badge failed">Failed</span>
                      </div>
                      <strong>
                        {incident.productionDecision.selectedPolicyId}
                      </strong>
                      <p>
                        Recommendation: {humanize(
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
                        Recommendation: {humanize(
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
                        Final action: {humanize(
                          incident.validation.finalAction
                        )}
                      </strong>
                      <p>{incident.validation.summary}</p>
                      <small>
                        Automatic action: {incident.validation
                          .automaticActionAllowed
                          ? "allowed"
                          : "blocked"}
                      </small>
                    </article>

                    <article className="decision-card human-review">
                      <div className="decision-card-header">
                        <span>Human-in-the-loop</span>
                        <span className="status-badge pending">
                          {incident.humanReview.case?.status ===
                          "pending-human-review"
                            ? "Pending"
                            : humanize(incident.humanReview.result)}
                        </span>
                      </div>
                      <strong>
                        Queue: {incident.humanReview.case?.queue ??
                          "Not assigned"}
                      </strong>
                      <p>
                        Policy: {incident.humanReview.case?.policyId ??
                          "Not available"}
                      </p>
                      <small>
                        Automatic action: {incident.humanReview.case
                          ?.automaticActionBlocked
                          ? "blocked"
                          : "not blocked"}
                      </small>
                    </article>
                  </div>
                </section>

                <aside className="panel release-panel">
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
                      {incident.candidateDecision.passed ? "PASS" : "FAIL"}
                    </strong>
                    <small>
                      {incident.validation.humanReviewRequired
                        ? "Human review enforced"
                        : "Automatic processing allowed"}
                    </small>
                  </div>
                  <label>Canary traffic</label>
                  <progress value="10" max="100" />
                  <strong>{canaryCandidateWeight}</strong>
                  <button className="primary-button" disabled>
                    Promote via Pipeline
                  </button>
                  <button className="secondary-button" disabled>
                    Rollback via Pipeline
                  </button>
                  <small className="muted-note">
                    Release actions will be connected through
                    OpenShift GitOps later in the lab.
                  </small>
                </aside>
              </div>
            )}
          </>
        )}

        {view === "evaluations" && (
          <section className="evaluation-page" id="evaluations">
            <div className="page-heading">
              <div>
                <h2>Agent evaluations</h2>
                <p>
                  Live regression checks against the deployed MCP
                  services, model endpoint, validation layer, and
                  human-review workflow.
                </p>
              </div>
              <button
                className="primary-button evaluation-run-button"
                onClick={loadEvaluation}
                disabled={evaluationLoading}
              >
                {evaluationLoading ? "Running..." : "Run evaluation"}
              </button>
            </div>

            {evaluationError && (
              <section className="panel error-panel">
                Unable to run the evaluation: {evaluationError}
              </section>
            )}

            {evaluationLoading && !evaluation && (
              <section className="panel">
                Running the health-emergency regression suite...
              </section>
            )}

            {evaluation && (
              <>
                <section className="evaluation-summary-grid">
                  <article className="metric-card">
                    <span>Suite status</span>
                    <strong
                      className={
                        evaluation.status === "passed"
                          ? "success-text"
                          : "danger-text"
                      }
                    >
                      {evaluation.status.toUpperCase()}
                    </strong>
                    <small>{evaluation.suite}</small>
                  </article>
                  <article className="metric-card">
                    <span>Cases</span>
                    <strong>{evaluation.caseCount}</strong>
                    <small>Live regression case</small>
                  </article>
                  <article className="metric-card">
                    <span>Checks passed</span>
                    <strong>
                      {evaluation.passedChecks}/{evaluation.checkCount}
                    </strong>
                    <small>{evaluation.failedChecks} failed</small>
                  </article>
                  <article className="metric-card">
                    <span>Model</span>
                    <strong className="model-name">
                      {evaluation.model}
                    </strong>
                    <small>Schema-constrained output</small>
                  </article>
                  <article className="metric-card">
                    <span>End-to-end latency</span>
                    <strong>
                      {(evaluation.totalLatencyMs / 1000).toFixed(2)} s
                    </strong>
                    <small>Current live run</small>
                  </article>
                </section>

                <div className="evaluation-layout">
                  <section className="panel">
                    <div className="section-heading">
                      <div>
                        <h2>Release gates</h2>
                        <p>{evaluation.description}</p>
                      </div>
                      <span
                        className={`status-badge ${
                          evaluation.status === "passed"
                            ? "passed"
                            : "failed"
                        }`}
                      >
                        Candidate {evaluation.status}
                      </span>
                    </div>

                    <div className="table-wrapper">
                      <table>
                        <thead>
                          <tr>
                            <th>Gate</th>
                            <th>Stable v1</th>
                            <th>Candidate v2</th>
                          </tr>
                        </thead>
                        <tbody>
                          {evaluation.releaseGates.map((gate) => (
                            <tr key={gate.name}>
                              <td>{gate.name}</td>
                              <td>
                                <span
                                  className={`result-pill ${
                                    gate.stable ? "pass" : "fail"
                                  }`}
                                >
                                  {gate.stable ? "PASS" : "FAIL"}
                                </span>
                              </td>
                              <td>
                                <span
                                  className={`result-pill ${
                                    gate.candidate ? "pass" : "fail"
                                  }`}
                                >
                                  {gate.candidate ? "PASS" : "FAIL"}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>

                  <aside className="panel evaluation-release-summary">
                    <h2>Release decision</h2>
                    <div className="release stable">
                      <span>Stable v1</span>
                      <strong className="danger-text">
                        {evaluation.stable.status.toUpperCase()}
                      </strong>
                      <small>
                        {humanize(evaluation.stable.recommendation)}
                      </small>
                    </div>
                    <div className="release candidate">
                      <span>Candidate v2</span>
                      <strong>
                        {evaluation.candidate.status.toUpperCase()}
                      </strong>
                      <small>
                        {humanize(evaluation.candidate.recommendation)}
                      </small>
                    </div>
                    <div className="release-gate">
                      <span>Evaluation gate</span>
                      <strong
                        className={
                          evaluation.status === "passed"
                            ? "success-text"
                            : "danger-text"
                        }
                      >
                        {evaluation.status === "passed"
                          ? "READY FOR PIPELINE"
                          : "BLOCKED"}
                      </strong>
                      <small>
                        Pipeline integration is the next lab phase.
                      </small>
                    </div>
                  </aside>
                </div>

                {evaluation.cases.map((evaluationCase) => (
                  <section className="panel evaluation-case" key={evaluationCase.caseId}>
                    <div className="section-heading">
                      <div>
                        <h2>{evaluationCase.caseId}</h2>
                        <p>{evaluationCase.scenario}</p>
                      </div>
                      <span
                        className={`status-badge ${
                          evaluationCase.status === "passed"
                            ? "passed"
                            : "failed"
                        }`}
                      >
                        {evaluationCase.status}
                      </span>
                    </div>
                    <div className="table-wrapper">
                      <table>
                        <thead>
                          <tr>
                            <th>Check</th>
                            <th>Expected</th>
                            <th>Actual</th>
                            <th>Result</th>
                          </tr>
                        </thead>
                        <tbody>
                          {evaluationCase.checks.map((check) => (
                            <tr key={check.id}>
                              <td>{check.name}</td>
                              <td>{displayValue(check.expected)}</td>
                              <td>{displayValue(check.actual)}</td>
                              <td>
                                <span
                                  className={`result-pill ${
                                    check.passed ? "pass" : "fail"
                                  }`}
                                >
                                  {check.passed ? "PASS" : "FAIL"}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                ))}

                <p className="evaluation-run-meta">
                  Run ID: {evaluation.runId} · Generated: {new Date(
                    evaluation.generatedAt
                  ).toLocaleString()}
                </p>
              </>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
