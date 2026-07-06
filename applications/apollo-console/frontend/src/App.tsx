import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
  version: string;
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
                className={metric.warning ? "warning-text" : ""}
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

        <div className="content-grid">
          <section className="panel incident-panel">
            <h2>Recent incident</h2>

            <div className="incident-summary">
              <div>
                <span>Case ID</span>
                <strong>APOLLO-001</strong>
              </div>
              <div>
                <span>Airline</span>
                <strong>Fedora Air</strong>
              </div>
              <div>
                <span>Scenario</span>
                <strong>Nova Health Emergency</strong>
              </div>
              <div>
                <span>Expected</span>
                <strong>Human review</strong>
              </div>
              <div>
                <span>Actual</span>
                <strong className="danger-text">
                  Automatic recommendation
                </strong>
              </div>
            </div>

            <div className="execution-flow">
              <div className="flow-step healthy">booking-mcp</div>
              <span>→</span>
              <div className="flow-step healthy">
                disruption-mcp
              </div>
              <span>→</span>
              <div className="flow-step failed">
                policy-mcp
                <small>Wrong policy selected</small>
              </div>
              <span>→</span>
              <div className="flow-step healthy">
                model decision
              </div>
              <span>→</span>
              <div className="flow-step healthy">
                case-management-mcp
              </div>
            </div>

            <h3>Policies returned</h3>

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
                <tr>
                  <td>FED-HEALTH-GENERAL-2027</td>
                  <td>10</td>
                  <td>automatic-voucher</td>
                  <td>Yes</td>
                  <td>—</td>
                </tr>
                <tr>
                  <td>FED-NOVA-HEALTH-EMERGENCY-2027</td>
                  <td>100</td>
                  <td>human-review</td>
                  <td>No</td>
                  <td>Yes</td>
                </tr>
              </tbody>
            </table>
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

            <button className="primary-button">Promote</button>
            <button className="secondary-button">Rollback</button>
          </aside>
        </div>
      </main>
    </div>
  );
}

export default App;
