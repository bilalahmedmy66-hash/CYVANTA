import { useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, CheckCircle2, Database, Network,
  RefreshCw, ShieldCheck, Target
} from "lucide-react";
import { apiRequest, getSession } from "./api";

function asList(value) {
  if (Array.isArray(value)) return value;
  if (!value || typeof value !== "object") return [];
  for (const key of ["items", "results", "data", "records", "authorizations", "executions", "missions", "events"]) {
    if (Array.isArray(value[key])) return value[key];
  }
  return [];
}

function display(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function DataTable({ columns, rows, emptyTitle, emptyText }) {
  if (!rows.length) {
    return <div className="workspace-empty"><Database size={22}/><b>{emptyTitle}</b><p>{emptyText}</p></div>;
  }
  return (
    <div className="workspace-table-wrap">
      <table className="workspace-table">
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || row.execution_id || row.mission_id || `${row.asset_id || "row"}-${index}`}>
              {columns.map((column) => <td key={column.key}>{column.render ? column.render(row) : display(row[column.key])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Panel({ eyebrow, title, children, action }) {
  return (
    <section className="panel workspace-panel">
      <div className="panel-head"><div><label>{eyebrow}</label><h2>{title}</h2></div>{action}</div>
      {children}
    </section>
  );
}

function ErrorNotice({ message }) {
  if (!message) return null;
  return <div className="workspace-error"><AlertTriangle size={16}/>{message}</div>;
}

function StatusLine({ loading, error, count, noun }) {
  if (loading) return <p className="workspace-data-status">Loading {noun}â€¦</p>;
  if (error) return <p className="workspace-data-status">This section could not be loaded. Other sections remain available.</p>;
  return <p className="workspace-data-status"><CheckCircle2 size={13}/> {count} {noun} returned by the backend</p>;
}

export default function WorkspacePage({ active }) {
  const [assets, setAssets] = useState([]);
  const [authorizations, setAuthorizations] = useState([]);
  const [missions, setMissions] = useState([]);
  const [executions, setExecutions] = useState([]);
  const [missionActions, setMissionActions] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});
  const [refreshKey, setRefreshKey] = useState(0);
  const activeKey = String(active || "").trim().toLowerCase();
  const session = getSession();
  const canReviewAuthorizations = ["owner", "admin", "reviewer"].includes(
    String(session?.organizationRole || "").toLowerCase()
  );

  async function decideAuthorization(record, decision) {
    const authorizationId = record.authorization_id || record.id;
    if (!authorizationId) {
      window.alert("This authorization record does not contain an authorization ID. No decision was submitted.");
      return;
    }

    const reason = window.prompt(
      `${decision === "approve" ? "Approval" : "Rejection"} reason (at least 5 characters):`
    );
    if (reason === null) return;
    if (reason.trim().length < 5 || reason.trim().length > 1000) {
      window.alert("Please enter a reason between 5 and 1000 characters.");
      return;
    }

    const assetLabel = record.asset_name || record.name || "this asset";
    if (!window.confirm(`Confirm ${decision} for ${assetLabel}? The decision will be recorded in the audit history.`)) {
      return;
    }

    try {
      await apiRequest(`/assets/authorizations/${encodeURIComponent(authorizationId)}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reason: reason.trim() }),
      });
      window.alert(`Authorization ${decision}d successfully.`);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      window.alert(error?.message || "The authorization decision could not be submitted.");
    }
  }

  useEffect(() => {
    let live = true;
    const setResult = (key, setter, value) => {
      if (live) {
        setter(value);
        setErrors((previous) => ({ ...previous, [key]: "" }));
      }
    };
    const setFailure = (key, error) => {
      if (live) setErrors((previous) => ({
        ...previous,
        [key]: error?.message || `Unable to load ${key} from the CYVANTA API.`
      }));
    };
    const requestList = async (key, path, setter) => {
      try {
        const result = await apiRequest(path);
        setResult(key, setter, asList(result));
      } catch (error) {
        setFailure(key, error);
        setResult(key, setter, []);
      }
    };

    async function load() {
      setLoading(true);
      setErrors({});
      try {
        if (activeKey === "attack surface") {
          await requestList("assets", "/assets", setAssets);
        } else if (activeKey === "authorizations") {
          await requestList("authorizations", "/assets/authorizations", setAuthorizations);
        } else if (activeKey === "execution queue") {
          const tasks = [
            requestList("missions", "/missions", setMissions),
            requestList("executions", "/executions", setExecutions)
          ];
          await Promise.all(tasks);

          // Action history is fetched per mission so one failed mission does not hide the others.
          const missionSnapshot = await apiRequest("/missions").then(asList).catch(() => []);
          const actionGroups = await Promise.all(missionSnapshot.slice(0, 25).map(async (mission) => {
            const missionId = mission.id || mission.mission_id;
            if (!missionId) return [];
            try {
              const rows = asList(await apiRequest(`/missions/${encodeURIComponent(missionId)}/actions`));
              return rows.map((action) => ({ ...action, mission_title: mission.title || missionId }));
            } catch {
              return [];
            }
          }));
          if (live) setMissionActions(actionGroups.flat());
        } else if (activeKey === "evidence vault") {
          let executionRows = [];
          try {
            executionRows = asList(await apiRequest("/executions"));
            setResult("executions", setExecutions, executionRows);
          } catch (error) {
            setFailure("executions", error);
            setResult("executions", setExecutions, []);
          }
          const eventGroups = await Promise.all(executionRows.slice(0, 12).map(async (execution) => {
            const executionId = execution.id || execution.execution_id;
            if (!executionId) return [];
            try {
              return asList(await apiRequest(`/executions/${encodeURIComponent(executionId)}/events?limit=25&offset=0`));
            } catch {
              return [];
            }
          }));
          if (live) setEvents(eventGroups.flat());
        }
      } finally {
        if (live) setLoading(false);
      }
    }
    load().catch((error) => {
      if (live) setErrors((previous) => ({ ...previous, page: error?.message || "Unexpected workspace loading error." }));
    });
    return () => { live = false; };
  }, [active, refreshKey]);

  const refresh = (
    <button className="workspace-refresh" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}>
      <RefreshCw size={14}/> {loading ? "Refreshing" : "Refresh data"}
    </button>
  );

  const content = useMemo(() => {
    if (activeKey === "attack surface") return <>
      <div className="workspace-intro"><Target/><div><b>Registered assets</b><p>Assets returned by the CYVANTA backend. Only assets registered in your organization are shown.</p></div></div>
      <ErrorNotice message={errors.assets}/>
      <Panel eyebrow="01 / INVENTORY" title="Asset inventory" action={refresh}>
        <StatusLine loading={loading} error={errors.assets} count={assets.length} noun="assets"/>
        <DataTable rows={assets} columns={[
          {key:"name",label:"Asset"},{key:"asset_type",label:"Type"},{key:"identifier",label:"Identifier"},
          {key:"authorization_status",label:"Authorization"},{key:"assessment_enabled",label:"Assessment enabled"}
        ]} emptyTitle={loading ? "Loading registered assets" : "No assets returned"} emptyText="Register an authorized asset through the CYVANTA asset workflow. No sample assets are displayed."/>
      </Panel>
    </>;

    if (activeKey === "authorizations") return <>
      <div className="workspace-intro"><ShieldCheck/><div><b>Authorization records and approval status</b><p>Records are loaded from the organization-scoped authorization API, including their evidence references, scope and review status.</p></div></div>
      <ErrorNotice message={errors.authorizations}/>
      <Panel eyebrow="01 / GOVERNANCE" title="Authorization register" action={refresh}>
        <StatusLine loading={loading} error={errors.authorizations} count={authorizations.length} noun="authorization records"/>
        <DataTable rows={authorizations} columns={[
          {key:"asset_name",label:"Asset"},{key:"evidence_type",label:"Evidence type"},
          {key:"evidence_reference",label:"Evidence reference"},{key:"status",label:"Decision status"},
          {key:"submitted_by",label:"Submitted by"},{key:"reviewed_by",label:"Reviewed by"},
          {key:"valid_from",label:"Valid from"},{key:"expires_at",label:"Expires at"},
          ...(canReviewAuthorizations ? [{
            key:"review_action",
            label:"Review",
            render:(row) => {
              const status = String(row.status || row.decision_status || "").toLowerCase();
              if (status !== "pending") return <span className="workspace-data-status">No action</span>;
              return <div style={{display:"flex",gap:"8px",flexWrap:"wrap"}}>
                <button className="workspace-refresh" onClick={() => decideAuthorization(row, "approve")}>Approve</button>
                <button className="workspace-refresh" onClick={() => decideAuthorization(row, "reject")}>Reject</button>
              </div>;
            }
          }] : [])
        ]} emptyTitle={loading ? "Loading authorization records" : "No authorization records returned"} emptyText="No authorization records were returned for the current organization. This view does not infer approval from asset registration."/>
      </Panel>
    </>;

    if (activeKey === "execution queue") return <>
      <div className="workspace-intro"><Activity/><div><b>Missions, actions and execution records</b><p>Each data source loads independently. Missions marked planning-only are not active security operations; queue records do not imply a scanner or worker has executed.</p></div></div>
      <ErrorNotice message={errors.page}/>
      <Panel eyebrow="01 / PLANNING" title="Missions" action={refresh}>
        <StatusLine loading={loading} error={errors.missions} count={missions.length} noun="missions"/>
        <ErrorNotice message={errors.missions}/>
        <DataTable rows={missions} columns={[
          {key:"title",label:"Mission"},{key:"priority",label:"Priority"},{key:"status",label:"Status"},
          {key:"execution_mode",label:"Execution mode"},{key:"asset_id",label:"Asset ID"}
        ]} emptyTitle={loading ? "Loading missions" : "No missions returned"} emptyText="Create a mission through the authorized mission workflow. No placeholder queue items are shown."/>
      </Panel>
      <Panel eyebrow="02 / APPROVAL WORKFLOW" title="Mission actions">
        <StatusLine loading={loading} error={errors.missions} count={missionActions.length} noun="mission actions"/>
        <DataTable rows={missionActions} columns={[
          {key:"mission_title",label:"Mission"},{key:"id",label:"Action ID"},{key:"action_type",label:"Action type"},
          {key:"status",label:"Status"},{key:"decision",label:"Decision"},{key:"created_at",label:"Created"}
        ]} emptyTitle={loading ? "Loading mission actions" : "No mission actions returned"} emptyText="Actions will appear here when missions have action records. Approval remains required where the backend policy requires it."/>
      </Panel>
      <Panel eyebrow="03 / RUNTIME" title="Execution records">
        <StatusLine loading={loading} error={errors.executions} count={executions.length} noun="execution records"/>
        <ErrorNotice message={errors.executions}/>
        <DataTable rows={executions} columns={[
          {key:"id",label:"Execution ID"},{key:"status",label:"Status"},
          {key:"mission_id",label:"Mission ID"},{key:"created_at",label:"Created"}
        ]} emptyTitle={loading ? "Loading executions" : "No execution records returned"} emptyText="Execution records will appear here when the backend returns them. A failed mission request will not hide execution records, and vice versa."/>
      </Panel>
    </>;

    if (activeKey === "evidence vault") return <>
      <div className="workspace-intro"><Database/><div><b>Execution event history</b><p>Events are retrieved from the backend execution-history API. This view does not claim file evidence or cryptographic chain-of-custody unless the API supplies it.</p></div></div>
      <ErrorNotice message={errors.executions}/>
      <Panel eyebrow="01 / AUDIT HISTORY" title="Execution events" action={refresh}>
        <StatusLine loading={loading} error={errors.executions} count={events.length} noun="event records"/>
        <DataTable rows={events} columns={[
          {key:"id",label:"Event ID"},{key:"event_type",label:"Event type"},{key:"status",label:"Status"},
          {key:"actor_id",label:"Actor"},{key:"created_at",label:"Timestamp"}
        ]} emptyTitle={loading ? "Loading execution events" : "No events returned"} emptyText={executions.length ? "No event records were returned for the available executions." : "No executions are currently available to inspect."}/>
      </Panel>
    </>;

    if (activeKey === "intelligence graph") return <>
      <div className="workspace-intro"><Network/><div><b>Relationship intelligence</b><p>Graph visualization is intentionally unavailable until a verified graph-data endpoint is provided by the backend.</p></div></div>
      <Panel eyebrow="01 / RELATIONSHIPS" title="Intelligence graph">
        <div className="workspace-empty"><Network size={24}/><b>No graph data endpoint available</b><p>The current API contract does not expose a graph endpoint. CYVANTA will not fabricate entities, edges, or relationships.</p></div>
      </Panel>
    </>;
    return null;
  }, [active, assets, authorizations, missions, executions, missionActions, events, loading, errors, refresh, canReviewAuthorizations]);

  return (
    <div className="content workspace-content">
      <section className="welcome">
        <div><label><i/> CYVANTA WORKSPACE</label><h1>{active}</h1><p>Live records from the authorized CYVANTA backend.</p></div>
        <div className="standby"><i/> API-DRIVEN VIEW</div>
      </section>
      {content}
    </div>
  );
}
