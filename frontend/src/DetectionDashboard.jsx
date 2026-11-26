import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowDown,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Filter,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiRequest } from "./api";
import "./DetectionDashboard.css";

const PAGE_SIZE = 10;

async function fetchFindingsPage(page, statusFilter, severityFilter) {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(page * PAGE_SIZE),
  });

  if (statusFilter) params.set("status", statusFilter);
  if (severityFilter) params.set("severity", severityFilter);

  return apiRequest(`/platform/detections?${params.toString()}`);
}

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
];

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];

const SEVERITY_META = {
  critical: { label: "Critical", color: "#fb7185" },
  high: { label: "High", color: "#fb923c" },
  medium: { label: "Medium", color: "#facc15" },
  low: { label: "Low", color: "#4ade80" },
};

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function relativeTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function safeEvidence(value) {
  if (value === null || value === undefined) return "Not provided";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function getErrorMessage(error) {
  if (error.status === 403) {
    return "Platform operator authorization is required to access detection findings.";
  }
  if (error.status === 401) {
    return "Your session has expired. Please sign in again.";
  }
  return error.message || "Unable to load detection findings.";
}

function MetricCard({ label, value, detail, icon: Icon, tone }) {
  return (
    <article className={`detection-metric detection-metric-${tone}`}>
      <div className="detection-metric-top">
        <span>{label}</span>
        <span className="detection-metric-icon"><Icon size={18} /></span>
      </div>
      <div className="detection-metric-value">{value}</div>
      <div className="detection-metric-detail">{detail}</div>
    </article>
  );
}

function SeverityBadge({ severity }) {
  const key = String(severity || "unknown").toLowerCase();
  const meta = SEVERITY_META[key];

  return (
    <span className={`detection-severity detection-severity-${meta ? key : "unknown"}`}>
      <i />
      {meta?.label || severity || "Unknown"}
    </span>
  );
}

function StatusBadge({ status }) {
  const key = String(status || "unknown").toLowerCase();
  return (
    <span className={`detection-status detection-status-${key}`}>
      {key === "resolved" ? <CheckCircle2 size={12} /> :
        key === "acknowledged" ? <Clock3 size={12} /> :
          <AlertCircle size={12} />}
      {key.replaceAll("_", " ")}
    </span>
  );
}

function FindingTimeline({ events = [] }) {
  if (!events.length) {
    return (
      <div className="detection-empty-timeline">
        <Clock3 size={17} />
        <span>No lifecycle events have been recorded yet.</span>
      </div>
    );
  }

  return (
    <div className="detection-timeline">
      {events.map((event) => (
        <div className="detection-timeline-event" key={event.id}>
          <span className={`detection-timeline-dot detection-event-${event.event_type}`} />
          <div>
            <div className="detection-timeline-heading">
              <strong>{String(event.event_type || "event").replaceAll("_", " ")}</strong>
              <time>{formatDate(event.created_at)}</time>
            </div>
            {event.reason && <p>{event.reason}</p>}
            {event.details?.previous_status && (
              <small>
                {event.details.previous_status} <ArrowDown size={11} /> {event.details.new_status}
              </small>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function FindingDetails({ finding, onClose, onAction, busy }) {
  const [action, setAction] = useState("");
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState("");


  if (!finding) return null;

  async function submitAction(event) {
    event.preventDefault();
    const cleanReason = reason.trim();

    if (cleanReason.length < 5) {
      setFormError("Please enter at least 5 non-whitespace characters.");
      return;
    }
    if (cleanReason.length > 1000) {
      setFormError("Reason cannot exceed 1,000 characters.");
      return;
    }

    try {
      await onAction(finding, action, cleanReason);
      setAction("");
      setReason("");
      setFormError("");
    } catch (error) {
      setFormError(error.message);
    }
  }

  const canAcknowledge = finding.status === "open";
  const canResolve = finding.status === "open" || finding.status === "acknowledged";

  return (
    <div className="detection-drawer-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside className="detection-drawer" aria-label="Finding details">
        <div className="detection-drawer-header">
          <div>
            <span className="detection-eyebrow">DETECTION RECORD</span>
            <h2>Finding details</h2>
          </div>
          <button className="detection-icon-button" onClick={onClose} aria-label="Close details">
            <X size={19} />
          </button>
        </div>

        <div className="detection-drawer-content">
          <div className="detection-detail-tags">
            <SeverityBadge severity={finding.severity} />
            <StatusBadge status={finding.status} />
          </div>

          <h3>{finding.title}</h3>
          <p className="detection-detail-description">{finding.description}</p>

          <div className="detection-detail-grid">
            <div><span>RULE ID</span><strong>{finding.rule_id}</strong></div>
            <div><span>OCCURRENCES</span><strong>{finding.occurrence_count ?? 0}</strong></div>
            <div><span>FIRST DETECTED</span><strong>{formatDate(finding.first_detected_at)}</strong></div>
            <div><span>LAST DETECTED</span><strong>{formatDate(finding.last_detected_at)}</strong></div>
          </div>

          <section className="detection-detail-section">
            <div className="detection-section-heading">
              <h4>Evidence</h4>
              <span>RESTRICTED DATA</span>
            </div>
            <pre className="detection-evidence">{safeEvidence(finding.evidence)}</pre>
          </section>

          <section className="detection-detail-section">
            <div className="detection-section-heading">
              <h4>Investigation timeline</h4>
              <span>{finding.events?.length || 0} EVENTS</span>
            </div>
            <FindingTimeline events={finding.events || []} />
          </section>

          {(canAcknowledge || canResolve) && (
            <section className="detection-action-panel">
              <div className="detection-section-heading">
                <h4>Update finding status</h4>
                <span>AUDITED ACTION</span>
              </div>

              <div className="detection-action-buttons">
                {canAcknowledge && (
                  <button
                    type="button"
                    className="detection-action-secondary"
                    onClick={() => { setAction("acknowledge"); setFormError(""); }}
                    disabled={busy}
                  >
                    <Check size={15} /> Acknowledge
                  </button>
                )}
                {canResolve && (
                  <button
                    type="button"
                    className="detection-action-primary"
                    onClick={() => { setAction("resolve"); setFormError(""); }}
                    disabled={busy}
                  >
                    <ShieldCheck size={15} /> Resolve finding
                  </button>
                )}
              </div>

              {action && (
                <form className="detection-reason-form" onSubmit={submitAction}>
                  <label htmlFor="detection-action-reason">
                    REASON FOR {action.toUpperCase()}ING
                  </label>
                  <textarea
                    id="detection-action-reason"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="Document the reason for this status change..."
                    minLength={5}
                    maxLength={1000}
                    rows={4}
                    required
                  />
                  <div className="detection-reason-footer">
                    <span>{reason.length}/1000 characters</span>
                    <div>
                      <button type="button" onClick={() => setAction("")} disabled={busy}>Cancel</button>
                      <button type="submit" disabled={busy}>
                        {busy ? <LoaderCircle className="detection-spin" size={14} /> : <Check size={14} />}
                        Confirm
                      </button>
                    </div>
                  </div>
                  {formError && <p className="detection-form-error">{formError}</p>}
                </form>
              )}
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}

export default function DetectionDashboard() {
  const [findings, setFindings] = useState([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  const loadFindings = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) setRefreshing(true);
    else setLoading(true);

    setError("");

    try {
      const result = await fetchFindingsPage(page, statusFilter, severityFilter);

      setFindings(Array.isArray(result.items) ? result.items : []);
      setTotal(Number(result.total) || 0);
      setLastUpdated(new Date());
    } catch (err) {
      setError(getErrorMessage(err));
      setFindings([]);
      setTotal(0);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [page, statusFilter, severityFilter]);

  useEffect(() => {
    let active = true;

    async function loadInitialFindings() {
      try {
        const result = await fetchFindingsPage(page, statusFilter, severityFilter);

        if (!active) return;

        setFindings(Array.isArray(result.items) ? result.items : []);
        setTotal(Number(result.total) || 0);
        setLastUpdated(new Date());
        setError("");
      } catch (err) {
        if (!active) return;
        setError(getErrorMessage(err));
        setFindings([]);
        setTotal(0);
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadInitialFindings();

    return () => {
      active = false;
    };
  }, [page, statusFilter, severityFilter]);

  const filteredFindings = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return findings;

    return findings.filter((item) => [
      item.title,
      item.description,
      item.rule_id,
      item.id,
    ].some((value) => String(value || "").toLowerCase().includes(term)));
  }, [findings, search]);

  const counts = useMemo(() => {
    const result = {
      open: 0,
      acknowledged: 0,
      resolved: 0,
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
    };

    findings.forEach((finding) => {
      if (Object.hasOwn(result, finding.status)) result[finding.status] += 1;
      const severity = String(finding.severity || "").toLowerCase();
      if (Object.hasOwn(result, severity)) result[severity] += 1;
    });

    return result;
  }, [findings]);

  const severityData = useMemo(() => (
    SEVERITY_ORDER.map((key) => ({
      name: SEVERITY_META[key].label,
      count: counts[key],
      fill: SEVERITY_META[key].color,
    }))
  ), [counts]);

  const trendData = useMemo(() => {
    const buckets = Array.from({ length: 7 }, (_, index) => {
      const date = new Date();
      date.setDate(date.getDate() - (6 - index));
      return {
        key: date.toLocaleDateString(),
        day: date.toLocaleDateString([], { weekday: "short" }),
        count: 0,
      };
    });

    findings.forEach((finding) => {
      const date = new Date(finding.first_detected_at);
      if (Number.isNaN(date.getTime())) return;
      const bucket = buckets.find((item) => item.key === date.toLocaleDateString());
      if (bucket) bucket.count += 1;
    });

    return buckets;
  }, [findings]);

  async function openFinding(finding) {
    setSelected({ ...finding, events: [] });
    try {
      const detail = await apiRequest(`/platform/detections/${finding.id}`);
      setSelected(detail);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }

  async function handleAction(finding, action, reason) {
    setActionBusy(true);
    try {
      const updated = await apiRequest(
        `/platform/detections/${finding.id}/${action}`,
        {
          method: "POST",
          body: JSON.stringify({ reason }),
        },
      );

      const detail = await apiRequest(`/platform/detections/${finding.id}`);
      setSelected(detail);
      await loadFindings({ quiet: true });
      return updated;
    } catch (err) {
      throw new Error(getErrorMessage(err), { cause: err });
    } finally {
      setActionBusy(false);
    }
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <main className="detection-page">
      <header className="detection-header">
        <div>
          <div className="detection-eyebrow"><span /> SECURITY OPERATIONS / DETECTION CENTRE</div>
          <h1>Detection <span>&</span> Alerts</h1>
          <p>Monitor platform-wide security findings, investigate evidence and manage alert lifecycles.</p>
        </div>
        <div className="detection-header-actions">
          <div className="detection-live-indicator"><i /> API CONNECTED</div>
          <button
            className="detection-refresh-button"
            onClick={() => loadFindings({ quiet: true })}
            disabled={refreshing || loading}
          >
            <RefreshCw size={15} className={refreshing ? "detection-spin" : ""} />
            Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="detection-error-banner" role="alert">
          <AlertTriangle size={17} />
          <span>{error}</span>
          <button onClick={() => loadFindings()} aria-label="Retry"><RefreshCw size={14} /></button>
        </div>
      )}

      <section className="detection-metrics-grid">
        <MetricCard label="OPEN FINDINGS" value={loading ? "—" : counts.open} detail="Awaiting review" icon={AlertCircle} tone="open" />
        <MetricCard label="ACKNOWLEDGED" value={loading ? "—" : counts.acknowledged} detail="Under investigation" icon={Clock3} tone="ack" />
        <MetricCard label="RESOLVED" value={loading ? "—" : counts.resolved} detail="Marked as resolved" icon={CheckCircle2} tone="resolved" />
        <MetricCard label="TOTAL MATCHES" value={loading ? "—" : total} detail="Current API filter" icon={Activity} tone="total" />
      </section>

      <section className="detection-analytics-grid">
        <article className="detection-panel detection-trend-panel">
          <div className="detection-panel-heading">
            <div><span className="detection-eyebrow">SIGNAL ACTIVITY</span><h2>Detection activity</h2></div>
            <span className="detection-panel-note">LAST 7 DAYS · CURRENT PAGE</span>
          </div>
          <div className="detection-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trendData} margin={{ top: 12, right: 10, left: -22, bottom: 0 }}>
                <defs>
                  <linearGradient id="detectionTrendFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#45d6b0" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#45d6b0" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#20313c" strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="day" tick={{ fill: "#718897", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fill: "#718897", fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: "#101c26", border: "1px solid #29404d", borderRadius: 9, color: "#e6f0f2", fontSize: 12 }}
                  labelStyle={{ color: "#8ba2ad" }}
                />
                <Area type="monotone" dataKey="count" name="Findings" stroke="#45d6b0" strokeWidth={2} fill="url(#detectionTrendFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="detection-panel detection-severity-panel">
          <div className="detection-panel-heading">
            <div><span className="detection-eyebrow">RISK CLASSIFICATION</span><h2>Severity distribution</h2></div>
          </div>
          <div className="detection-severity-list">
            {severityData.map((item) => (
              <div className="detection-severity-row" key={item.name}>
                <span><i style={{ background: item.fill }} />{item.name}</span>
                <strong>{loading ? "—" : item.count}</strong>
              </div>
            ))}
          </div>
          <div className="detection-severity-foot">Based on findings in the current result page.</div>
        </article>
      </section>

      <section className="detection-panel detection-findings-panel">
        <div className="detection-panel-heading detection-findings-heading">
          <div><span className="detection-eyebrow">PLATFORM INTELLIGENCE</span><h2>Detection findings</h2></div>
          <span className="detection-panel-note">{total} TOTAL RECORDS</span>
        </div>

        <div className="detection-toolbar">
          <label className="detection-search">
            <Search size={16} />
            <input
              type="search"
              placeholder="Search this page by title, rule or ID..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>

          <label className="detection-select-wrap">
            <Filter size={14} />
            <select value={statusFilter} onChange={(event) => { setLoading(true); setStatusFilter(event.target.value); setPage(0); }}>
              {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>

          <label className="detection-select-wrap">
            <AlertCircle size={14} />
            <select value={severityFilter} onChange={(event) => { setLoading(true); setSeverityFilter(event.target.value); setPage(0); }}>
              <option value="">All severities</option>
              {SEVERITY_ORDER.map((value) => <option key={value} value={value}>{SEVERITY_META[value].label}</option>)}
            </select>
          </label>
        </div>

        <div className="detection-table-wrap">
          <table className="detection-table">
            <thead>
              <tr>
                <th>FINDING</th>
                <th>RULE</th>
                <th>SEVERITY</th>
                <th>STATUS</th>
                <th>OCCURRENCES</th>
                <th>LAST DETECTED</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="7" className="detection-table-message"><LoaderCircle className="detection-spin" size={19} /> Loading platform findings...</td></tr>
              ) : filteredFindings.length ? (
                filteredFindings.map((finding) => (
                  <tr key={finding.id} onClick={() => openFinding(finding)} tabIndex={0} onKeyDown={(event) => {
                    if (event.key === "Enter") openFinding(finding);
                  }}>
                    <td><div className="detection-finding-title">{finding.title}</div><small>{finding.id}</small></td>
                    <td><code>{finding.rule_id}</code></td>
                    <td><SeverityBadge severity={finding.severity} /></td>
                    <td><StatusBadge status={finding.status} /></td>
                    <td className="detection-occurrences">{finding.occurrence_count ?? 0}</td>
                    <td><span className="detection-date">{relativeTime(finding.last_detected_at)}</span></td>
                    <td><button className="detection-row-open" aria-label="Open finding details" onClick={(event) => { event.stopPropagation(); openFinding(finding); }}><ArrowUpRight size={16} /></button></td>
                  </tr>
                ))
              ) : (
                <tr><td colSpan="7" className="detection-table-message">
                  <ShieldCheck size={22} />
                  <strong>{error ? "Findings unavailable" : "No findings to display"}</strong>
                  <span>{error ? "Check your operator access and API connection." : "No records match the current filters. This is not a declaration that the platform is threat-free."}</span>
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="detection-table-footer">
          <span>Showing {filteredFindings.length} of {total} matching records</span>
          <div className="detection-pagination">
            <button disabled={page <= 0 || loading} onClick={() => { setLoading(true); setPage((value) => Math.max(0, value - 1)); }}><ChevronLeft size={15} /> Previous</button>
            <span>Page {page + 1} / {pageCount}</span>
            <button disabled={(page + 1) * PAGE_SIZE >= total || loading} onClick={() => { setLoading(true); setPage((value) => value + 1); }}>Next <ChevronRight size={15} /></button>
          </div>
        </div>
      </section>

      <footer className="detection-footer">
        <span><ShieldAlert size={13} /> ALERT-ONLY MODE · NO CONTAINMENT ACTIONS</span>
        <span>{lastUpdated ? `LAST UPDATED ${formatDate(lastUpdated)}` : "WAITING FOR API"}</span>
      </footer>

      {selected && (
        <FindingDetails
          key={selected.id}
          finding={selected}
          onClose={() => setSelected(null)}
          onAction={handleAction}
          busy={actionBusy}
        />
      )}
    </main>
  );
}
