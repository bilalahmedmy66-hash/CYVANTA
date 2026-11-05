import { useEffect, useState, cloneElement } from "react";
import { Activity, ArrowRight, Eye, EyeOff, Hexagon, LockKeyhole, ShieldCheck } from "lucide-react";
import { acceptOrganizationInvitation, authenticate, clearSession, getSession, registerAccount, verifySession } from "./api";

export default function AuthGate({ children }) {
  const [session, setSession] = useState(() => getSession());
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organization, setOrganization] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(Boolean(getSession()));
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    if (!getSession()) {
      setChecking(false);
      return () => { active = false; };
    }
    verifySession()
      .then((valid) => { if (active) setSession(valid); })
      .catch((err) => { if (active) setError(err.message || "Session verification failed."); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      let next;

      if (mode === "register") {
        next = await registerAccount(email.trim(), password, organization.trim());
        if (inviteToken.trim()) {
          const accepted = await acceptOrganizationInvitation(inviteToken.trim());
          next = accepted.session;
        }
      } else if (mode === "invite") {
        await authenticate(email.trim(), password);
        const accepted = await acceptOrganizationInvitation(inviteToken.trim());
        next = accepted.session;
      } else {
        next = await authenticate(email.trim(), password);
      }

      setSession(next);
    } catch (err) {
      setError(err.message || "Unable to complete the requested CYVANTA account action.");
    } finally {
      setBusy(false);
    }
  }
  function handleLogout() {
    clearSession();
    setSession(null);
    setPassword("");
    setMode("login");
  }

  if (checking) {
    return <div className="auth-screen"><div className="auth-card auth-loading"><Activity size={22} /><b>VERIFYING SECURE SESSION</b><span>Checking your CYVANTA credentials...</span></div></div>;
  }

  if (session) {
    return cloneElement(children, { onSignOut: handleLogout });
  }

  return (
    <div className="auth-screen">
      <div className="auth-glow auth-glow-a" /><div className="auth-glow auth-glow-b" />
      <section className="auth-card">
        <div className="auth-brand"><span className="auth-brand-icon"><Hexagon size={27} /></span><div><b>CYVANTA</b><small>SECURITY INTELLIGENCE</small></div></div>
        <div className="auth-kicker"><ShieldCheck size={14} /> AUTHORIZED OPERATOR ACCESS</div>
        <h1>{mode === "login" ? "Welcome back." : mode === "register" ? "Create workspace." : "Accept invitation."}</h1>
        <p className="auth-intro">{mode === "login" ? "Authenticate to access your organization's security operations environment." : mode === "register" ? "Register an operator account. If you have a reviewer invitation, you can accept it here too." : "Sign in with the exact email address that received the reviewer invitation, then enter your secure token."}</p>
        <form onSubmit={handleSubmit} className="auth-form">
          <label htmlFor="cyvanta-email">EMAIL ADDRESS</label>
          <input id="cyvanta-email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="operator@company.com" />
          {mode === "register" && <><label htmlFor="cyvanta-org">ORGANIZATION NAME</label><input id="cyvanta-org" type="text" required minLength={2} maxLength={150} value={organization} onChange={(e) => setOrganization(e.target.value)} placeholder="Your organization" /></>}
          {mode !== "login" && <><label htmlFor="cyvanta-invitation">REVIEWER INVITATION TOKEN</label><input id="cyvanta-invitation" type="text" required={mode === "invite"} minLength={mode === "invite" ? 32 : 0} maxLength={256} autoComplete="off" value={inviteToken} onChange={(e) => setInviteToken(e.target.value)} placeholder="Paste the secure invitation token" /></>}
          <label htmlFor="cyvanta-password">PASSWORD</label>
          <div className="auth-password"><input id="cyvanta-password" type={showPassword ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={mode === "register" ? 12 : 1} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={mode === "register" ? "At least 12 characters" : "Enter your password"} /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div>
          {error && <div className="auth-error" role="alert"><LockKeyhole size={15} /> {error}</div>}
          <button className="auth-submit" type="submit" disabled={busy}>{busy ? "PLEASE WAIT..." : mode === "login" ? "SECURE SIGN IN" : mode === "invite" ? "ACCEPT INVITATION" : "CREATE ACCOUNT"}{!busy && <ArrowRight size={17} />}</button>
        </form>
        <div className="auth-switch">{mode === "register" ? "Already have an account?" : mode === "invite" ? "Want to sign in normally?" : "New to CYVANTA?"}<button onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); setInviteToken(""); }}> {mode === "login" ? "Create an account" : "Sign in"}</button>{mode === "login" && <button onClick={() => { setMode("invite"); setError(""); }}> Have an invitation token?</button>}</div>
        <div className="auth-foot"><span><i /> API AUTHENTICATION REQUIRED</span><span>SESSION TOKEN | TAB-SCOPED</span></div>
      </section>
      <div className="auth-security-note"><LockKeyhole size={13} /> Credentials are sent only to your configured CYVANTA API. Passwords are never stored in the browser session.</div>
    </div>
  );
}
