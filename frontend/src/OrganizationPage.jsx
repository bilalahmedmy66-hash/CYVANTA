import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Copy, Mail, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { apiRequest, getSession } from "./api";

function dateLabel(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function Notice({ children, error = false }) {
  if (!children) return null;
  return <div className={`org-message${error ? " error" : ""}`}>{children}</div>;
}

export default function OrganizationPage() {
  const session = getSession();
  const isOwner = session?.organizationRole === "owner";
  const [email, setEmail] = useState("");
  const [members, setMembers] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [handoff, setHandoff] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    if (!isOwner) return;
    setLoading(true);
    setError("");
    try {
      const [memberRows, invitationRows] = await Promise.all([
        apiRequest("/organizations/members"),
        apiRequest("/organizations/invitations")
      ]);
      setMembers(Array.isArray(memberRows) ? memberRows : []);
      setInvitations(Array.isArray(invitationRows) ? invitationRows : []);
    } catch (err) {
      setError(err.message || "Unable to load organization membership.");
    } finally {
      setLoading(false);
    }
  }, [isOwner]);

  useEffect(() => { load(); }, [load, refreshKey]);

  async function createInvitation(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    setHandoff(null);
    try {
      const result = await apiRequest("/organizations/invitations", {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), role: "reviewer" })
      });
      setHandoff(result);
      setEmail("");
      setMessage("Invitation created. This is a development handoff; no email has been sent.");
      setRefreshKey((value) => value + 1);
    } catch (err) {
      setError(err.message || "Invitation could not be created.");
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(member) {
    const confirmed = window.confirm(
      `Remove ${member.email} from this organization? This removes only their organization membership.`
    );
    if (!confirmed) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await apiRequest(`/organizations/members/${encodeURIComponent(member.user_id)}`, {
        method: "DELETE"
      });
      setMessage(`${member.email} was removed from this organization.`);
      setRefreshKey((value) => value + 1);
    } catch (err) {
      setError(err.message || "Member could not be removed.");
    } finally {
      setBusy(false);
    }
  }

  async function copyToken() {
    if (!handoff?.invitation_token) return;
    try {
      await navigator.clipboard.writeText(handoff.invitation_token);
      setMessage("Invitation token copied. Share it only with the invited person.");
    } catch {
      setError("Clipboard access was unavailable. Select and copy the token manually.");
    }
  }

  if (!isOwner) {
    return (
      <div className="content workspace-content">
        <section className="welcome">
          <div><label><i /> CYVANTA GOVERNANCE</label><h1>Organization</h1><p>Membership and invitation controls.</p></div>
          <div className="standby"><i /> ROLE RESTRICTED</div>
        </section>
        <div className="org-permission">
          <ShieldCheck size={20} />
          <h3>Owner permission required</h3>
          <p>Your current organization role is <b>{session?.organizationRole || "unknown"}</b>. The backend currently reserves member and invitation management for organization owners. Your access has not been elevated.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="content workspace-content">
      <section className="welcome">
        <div><label><i /> CYVANTA GOVERNANCE</label><h1>Organization</h1><p>Manage organization membership and invite reviewers for authorization decisions.</p></div>
        <div className="standby"><i /> OWNER CONTROLS</div>
      </section>

      <div className="workspace-intro">
        <Users />
        <div><b>Separation of duties</b><p>Invited users receive the reviewer role only after accepting an invitation with the matching account email. Reviewers cannot manage members or perform authorization lifecycle actions.</p></div>
      </div>

      <Notice error>{error}</Notice>
      <Notice>{message}</Notice>

      <div className="org-grid">
        <section className="panel workspace-panel">
          <div className="panel-head"><div><label>01 / ACCESS</label><h2>Invite a reviewer</h2></div><Mail size={18} /></div>
          <form className="org-form" onSubmit={createInvitation}>
            <label htmlFor="org-invite-email">INVITEE EMAIL ADDRESS</label>
            <input id="org-invite-email" type="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="reviewer@company.com" />
            <label>ASSIGNED ROLE</label>
            <div><span className="org-role">Reviewer</span><p className="org-muted">Fixed by the backend invitation policy. Other roles cannot be assigned here.</p></div>
            <button className="org-primary" type="submit" disabled={busy}><Mail size={14} /> {busy ? "CREATING INVITATION..." : "CREATE INVITATION"}</button>
          </form>
          {handoff?.invitation_token && (
            <div className="org-handoff">
              <strong>One-time development handoff</strong>
              <p>No email provider is configured. Copy this token and deliver it securely to the invited person. It expires at {dateLabel(handoff.expires_at)}. It is not shown again after leaving this page.</p>
              <textarea readOnly value={handoff.invitation_token} aria-label="Invitation token" />
              <div className="org-inline-actions">
                <button type="button" className="org-copy" onClick={copyToken}><Copy size={13} /> COPY TOKEN</button>
              </div>
            </div>
          )}
        </section>

        <section className="panel workspace-panel">
          <div className="panel-head"><div><label>02 / MEMBERSHIP</label><h2>Organization members</h2></div><button className="workspace-refresh" type="button" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}><RefreshCw size={14} /> {loading ? "Refreshing" : "Refresh"}</button></div>
          {loading ? <p className="org-muted">Loading organization members...</p> : members.length === 0 ? <div className="workspace-empty"><Users size={22} /><b>No members returned</b><p>The backend returned no organization members.</p></div> : (
            <div className="workspace-table-wrap">
              <table className="workspace-table">
                <thead><tr><th>Email</th><th>Role</th><th>Action</th></tr></thead>
                <tbody>{members.map((member) => (
                  <tr key={member.user_id}>
                    <td>{member.email}</td>
                    <td><span className="org-role">{member.role}</span></td>
                    <td>{member.role === "owner" ? <span className="org-muted">Protected</span> : <button className="org-danger" type="button" disabled={busy} onClick={() => removeMember(member)}>Remove</button>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <section className="panel workspace-panel">
        <div className="panel-head"><div><label>03 / INVITATION REGISTER</label><h2>Reviewer invitations</h2></div><span className="org-role">{invitations.length} records</span></div>
        {loading ? <p className="org-muted">Loading invitations...</p> : invitations.length === 0 ? <div className="workspace-empty"><Mail size={22} /><b>No invitations returned</b><p>Invitations created by this organization will appear here. Invitation tokens are never included in this list.</p></div> : (
          <div className="workspace-table-wrap">
            <table className="workspace-table">
              <thead><tr><th>Email</th><th>Role</th><th>Status</th><th>Created</th><th>Expires</th></tr></thead>
              <tbody>{invitations.map((invitation) => (
                <tr key={invitation.id}>
                  <td>{invitation.email}</td><td><span className="org-role">{invitation.role}</span></td>
                  <td>{invitation.status || (invitation.accepted_at ? "accepted" : invitation.revoked_at ? "revoked" : "pending")}</td>
                  <td>{dateLabel(invitation.created_at)}</td><td>{dateLabel(invitation.expires_at)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
      <p className="org-muted"><AlertTriangle size={13} /> Invitation creation currently uses development handoff only. Production email delivery is not configured by the backend.</p>
    </div>
  );
}
