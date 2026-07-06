import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
  version: string;
};

type ExecutionStep = {
  component: string;
  status: "healthy" | "failed" | "not-connected";
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
  execution: ExecutionStep[];
  policies: Policy[];
};

const metrics = [
  {
    label: "Agent status",
    value: "Degraded",
    detail: "Quality below target",
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
        setApiStatus(health.status);
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

        <section className="metrics">
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
              Platform healthy — agent quality degraded
            </strong>

            <p>
              Infrastructure and MCP services are available,
              but policy-selection quality is below target.
            </p>
          </div>
        </section>

        {incidentError && (
          <section className="panel error-panel">
            Unable to load the production incident:
            {" "}
            {incidentError}
          </section>
        )}

        {!incident && !incidentError && (
          <section className="panel">
            Loading the production incident from policy-mcp...
          </section>
        )}

        {incident && (
          <div className="content-grid">
            <section className="panel incident-panel">
              <h2>Recent incident</h2>

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
                  <span>Expected</span>
                  <strong>{incident.expectedAction}</strong>
                </div>

                <div>
                  <span>Actual</span>
                  <strong
                    className={
                      incident.passed
                        ? ""
                        : "danger-text"
                    }
                  >
                    {incident.actualAction ?? "No decision"}
                  </strong>
                </div>
              </div>

              <div className="execution-flow">
                {incident.execution.map((step, index) => (
                  <div
                    className="flow-entry"
                    key={step.component}
                  >
                    <div
                      className={`flow-step ${step.status}`}
                    >
                      {step.component.replace(/-/g, " ")}

                      {step.status === "failed" && (
                        <small>Wrong policy selected</small>
                      )}

                      {step.status === "not-connected" && (
                        <small>Not connected yet</small>
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

              <table>
                <thead>
                  <tr>
                    <th>Policy ID</th>
                    <th>Priority</th>
                    <th>Action</th>
                    <th>Selected</th>
                    <th>Expected</th>
                  </tr>
                </thead>

                <tbody>
                  {incident.policies.map((policy) => (
                    <tr key={policy.policyId}>
                      <td>{policy.policyId}</td>
                      <td>{policy.priority}</td>
                      <td>{policy.recommendedAction}</td>

                      <td>
                        {policy.policyId ===
                        incident.selectedPolicyId
                          ? "Yes"
                          : "No"}
                      </td>

                      <td>
                        {policy.policyId ===
                        incident.expectedPolicyId
                          ? "Yes"
                          : "No"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div
                className={
                  incident.passed
                    ? "decision-result passed"
                    : "decision-result failed"
                }
              >
                <strong>
                  {incident.passed
                    ? "Evaluation passed"
                    : "Evaluation failed"}
                </strong>

                <span>
                  Selected:{" "}
                  {incident.selectedPolicyId ?? "None"}
                </span>

                <span>
                  Expected: {incident.expectedPolicyId}
                </span>
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

              <label>Canary traffic</label>
              <progress value="10" max="100" />
              <strong>10%</strong>

              <button className="primary-button">
                Promote
              </button>

              <button className="secondary-button">
                Rollback
              </button>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
