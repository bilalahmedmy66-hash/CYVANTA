import { useEffect, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, Stars, Sparkles } from "@react-three/drei";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  Activity, AlertOctagon, ArrowUpRight, Bell, Boxes, ChevronDown,
  CircleDot, Command, Crosshair, Database, Fingerprint, Gauge, GitBranch,
  Globe2, Hexagon, Layers3, LockKeyhole, Menu, Network, Radio, Search,
  Settings2, Shield, ShieldAlert, ShieldCheck, ShieldEllipsis, MoreHorizontal,
  SlidersHorizontal, X
} from "lucide-react";
import "./App.css";
import AuthGate from "./AuthGate";
import { getSession } from "./api";
import WorkspacePage from "./WorkspacePage";
import OrganizationPage from "./OrganizationPage";

const navigation = [
  ["Command centre", Gauge, "OPERATIONS"],
  ["Attack surface", Crosshair, "OPERATIONS"],
  ["Authorizations", LockKeyhole, "GOVERNANCE"],
  ["Execution queue", Activity, "GOVERNANCE"],
  ["Intelligence graph", Network, "INTELLIGENCE"],
  ["Evidence vault", Database, "INTELLIGENCE"],
  ["Organization", Settings2, "GOVERNANCE"]
];

const pageMotion = {
  hidden: { opacity: 0, y: 14 },
  visible: (index) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, delay: index * 0.06, ease: "easeOut" }
  })
};

function IntelligenceCore() {
  const group = useRef();
  const ringA = useRef();
  const ringB = useRef();
  const reducedMotion = useReducedMotion();

  useFrame((state, delta) => {
    if (reducedMotion) return;
    if (group.current) group.current.rotation.y += delta * 0.075;
    if (ringA.current) ringA.current.rotation.z += delta * 0.11;
    if (ringB.current) ringB.current.rotation.x -= delta * 0.075;
  });

  return (
    <group ref={group}>
      <Float speed={reducedMotion ? 0 : 0.65} rotationIntensity={reducedMotion ? 0 : 0.08} floatIntensity={reducedMotion ? 0 : 0.12}>
        <mesh>
          <icosahedronGeometry args={[1.04, 2]} />
          <meshStandardMaterial color="#3b82a6" emissive="#22d3ee" emissiveIntensity={0.22} metalness={0.75} roughness={0.2} wireframe />
        </mesh>
        <mesh scale={0.79}>
          <icosahedronGeometry args={[1, 2]} />
          <meshPhysicalMaterial color="#171a3d" emissive="#312e81" emissiveIntensity={0.45} metalness={0.65} roughness={0.18} transparent opacity={0.78} />
        </mesh>
        <mesh ref={ringA} rotation={[0.8, 0.2, 0.2]}>
          <torusGeometry args={[1.39, 0.012, 12, 180]} />
          <meshBasicMaterial color="#22d3ee" />
        </mesh>
        <mesh ref={ringB} rotation={[1.2, 0.2, 0.8]}>
          <torusGeometry args={[1.56, 0.009, 10, 180]} />
          <meshBasicMaterial color="#8b5cf6" />
        </mesh>
        <mesh rotation={[0.3, 0.5, 0]}>
          <torusGeometry args={[1.22, 0.006, 8, 160]} />
          <meshBasicMaterial color="#f472b6" transparent opacity={0.55} />
        </mesh>
      </Float>
      <Sparkles count={55} scale={4.1} size={2} speed={reducedMotion ? 0 : 0.16} color="#8eeeff" />
    </group>
  );
}

function CoreView() {
  return (
    <div className="core-stage">
      <div className="core-grid" />
      <div className="core-spotlight" />
      <Canvas camera={{ position: [0, 0, 5.1], fov: 42 }} dpr={[1, 1.5]}>
        <ambientLight intensity={0.95} />
        <pointLight position={[3, 3, 4]} intensity={20} color="#22d3ee" />
        <pointLight position={[-3, -2, 2]} intensity={15} color="#8b5cf6" />
        <pointLight position={[0, 0, 1]} intensity={5} color="#f472b6" />
        <IntelligenceCore />
        <Stars radius={70} depth={35} count={700} factor={2} fade speed={0.18} />
      </Canvas>
      <div className="core-label top-label">CYVANTA INTELLIGENCE CORE</div>
      <div className="core-center"><i /> CORE STANDBY</div>
      <div className="core-label bottom-label">SPATIAL ENVIRONMENT <span>LOCAL VIEW / STANDBY</span></div>
    </div>
  );
}

function SparklinePlaceholder() {
  return (
    <div className="kpi-empty">
      <svg viewBox="0 0 116 24" role="img" aria-label="No trend data available">
        <path d="M1 18 H115" className="spark-base" />
        <path d="M2 15 L18 15 L29 11 L42 17 L56 17 L68 8 L81 13 L94 13 L114 5" className="spark-dash" />
      </svg>
      <span>AWAITING DATA</span>
    </div>
  );
}

function Metric({ icon: Icon, label, note, index }) {
  return (
    <motion.article className="metric" custom={index} variants={pageMotion} initial="hidden" animate="visible">
      <div className="metric-top">
        <span className="metric-icon"><Icon size={17} /></span>
        <span className="metric-label">{label}</span>
        <ArrowUpRight size={14} className="metric-arrow" />
      </div>
      <div className="metric-bottom">
        <strong>—</strong>
        <SparklinePlaceholder />
      </div>
      <small>{note}</small>
    </motion.article>
  );
}

function Dashboard({ onSignOut }) {
  const [operatorSession] = useState(() => getSession());
  const operatorEmail = operatorSession?.profile?.email || "Authenticated operator";
  const operatorName = operatorEmail.includes("@") ? operatorEmail.split("@")[0] : operatorEmail;
  const operatorInitials = operatorName.split(/[._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join("") || "OP";
  const [active, setActive] = useState("Command centre");
  const [menuOpen, setMenuOpen] = useState(false);
  // CYVANTA desktop sidebar toggle v8
  const [sidebarHidden, setSidebarHidden] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const time = now.toLocaleTimeString("en-GB", { hour12: false });
  const date = now.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });

  return (
    <div className={`shell${sidebarHidden ? " sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${menuOpen ? "opened" : ""}`}>
        <div className="brand">
          <div className="brand-icon"><Hexagon size={25} /></div>
          <div><b>CYVANTA</b><small>SECURITY INTELLIGENCE</small></div>
          <button className="close-menu" onClick={() => setMenuOpen(false)} aria-label="Close menu"><X size={18} /></button>
        </div>

        <button className="workspace">
          <span>C</span><div><b>Command workspace</b><small>Local environment</small></div><ChevronDown size={15} />
        </button>

        {["OPERATIONS", "GOVERNANCE", "INTELLIGENCE"].map((section) => (
          <div className="nav-group" key={section}>
            <label>{section}</label>
            {navigation.filter((item) => item[2] === section).map(([name, Icon]) => (
              <button key={name} title={name} className={`nav-item ${active === name ? "selected" : ""}`} onClick={() => { setActive(name); setMenuOpen(false); }}>
                <Icon size={17} /><span>{name}</span>{name === "Execution queue" && <span className="nav-dash">—</span>}
              </button>
            ))}
          </div>
        ))}

        <div className="sidebar-end">
          <div className="environment">
            <label><i /> ENVIRONMENT STATUS</label>
            <b>Awaiting connection</b>
            <p>Connect an authorized environment to receive verified telemetry.</p>
            <div><span>API CONNECTION</span><em>NOT CONNECTED</em></div>
          </div>
          <button className="nav-item settings-item"><Settings2 size={17} /><span>Settings</span></button>
          <div className="profile"><span>{operatorInitials}</span><div><b title={operatorEmail}>{operatorName}</b><small title={operatorSession?.organizationName || "No organization context"}>{operatorSession?.organizationName || operatorEmail}</small><small title={operatorEmail} style={{ overflowWrap: "anywhere" }}>{operatorEmail}</small></div><SlidersHorizontal size={16} /></div>
          <button type="button" className="sidebar-account-signout" onClick={onSignOut} style={{ width: "100%", marginTop: 12, marginBottom: 14, padding: "11px 14px", border: "1px solid rgba(139,124,255,.28)", borderRadius: 12, background: "rgba(139,124,255,.10)", color: "#F1F5FF", cursor: "pointer", fontSize: 12, fontWeight: 700, letterSpacing: ".08em", textAlign: "left" }}>SIGN OUT</button>
        </div>
      </aside>

      {menuOpen && <button className="scrim" onClick={() => setMenuOpen(false)} aria-label="Close navigation" />}

      <main className="main">
        <header className="topbar">
          <div className="crumb"><button type="button" onClick={() => setSidebarHidden((hidden) => !hidden)} className="desktop-sidebar-toggle" aria-label={sidebarHidden ? "Show sidebar" : "Hide sidebar"} title={sidebarHidden ? "Show sidebar" : "Hide sidebar"}><MoreHorizontal size={20} /></button><button onClick={() => setMenuOpen(true)} className="mobile-menu" aria-label="Open menu"><Menu size={19} /></button> CYVANTA <span>/</span> <b>{active}</b></div>
          <div className="top-actions">
            <div className="clock"><b>{time}</b><small>{date} · LOCAL TIME</small></div>
            <i className="divider" />
            <button onClick={() => setSearchOpen(true)} aria-label="Search"><Search size={18} /></button>
            <button className="bell" onClick={() => setNoticeOpen(!noticeOpen)} aria-label="Notifications"><Bell size={18} /><i /></button>
            <span className="avatar" title={operatorEmail}>{operatorInitials}</span>
          </div>
        </header>

        {active === "Organization" ? <OrganizationPage /> : active === "Command centre" ? <div className="content">
          <section className="welcome">
            <div>
              <label><i /> AUTONOMOUS SECURITY OPERATIONS</label>
              <h1>{active === "Command centre" ? <>See the whole <em>security picture.</em></> : active}</h1>
              <p>One spatial environment for authorized security intelligence, controlled action and verifiable outcomes.</p>
            </div>
            <div className="standby"><i /> SYSTEM STANDBY <span /> LIVE DATA UNAVAILABLE</div>
          </section>

          <section className="metrics">
            <Metric icon={ShieldCheck} label="AUTHORIZED ASSETS" note="No environment connected" index={0} />
            <Metric icon={Activity} label="ACTIVE EXECUTIONS" note="Awaiting verified telemetry" index={1} />
            <Metric icon={AlertOctagon} label="OPEN FINDINGS" note="No finding data received" index={2} />
            <Metric icon={Fingerprint} label="PENDING APPROVALS" note="No approval data received" index={3} />
          </section>

          <section className="spatial">
            <motion.article className="panel spatial-panel" variants={pageMotion} initial="hidden" animate="visible" custom={4}>
              <div className="panel-head"><div><label>01 / SPATIAL OVERVIEW</label><h2>Intelligence core</h2></div><span className="local"><Radio size={13} /> LOCAL VIEW</span></div>
              <CoreView />
              <div className="legend"><span><i className="cyan" /> INTELLIGENCE LAYER</span><span><i className="violet" /> CONTROL LAYER</span><span><i className="grey" /> AWAITING TELEMETRY</span></div>
            </motion.article>

            <div className="right-stack">
              <motion.article className="panel" variants={pageMotion} initial="hidden" animate="visible" custom={5}>
                <div className="panel-head"><div><label>02 / CONTROL POSTURE</label><h2>Operational safeguards</h2></div><Shield size={17} /></div>
                <div className="safeguards">
                  {[
                    [LockKeyhole, "Authorization gate", "Required before any action", "ENFORCED", "success"],
                    [ShieldEllipsis, "Least privilege", "Scoped access model", "ENFORCED", "success"],
                    [GitBranch, "Audit trail", "Append-only event history", "ENABLED", "info"],
                    [ShieldAlert, "Emergency stop", "Control available to operators", "AVAILABLE", "violet"]
                  ].map(([Icon, title, desc, state, tone]) => (
                    <div className="safe-row" key={title}>
                      <span className="safe-icon"><Icon size={16} /></span>
                      <div><b>{title}</b><small>{desc}</small></div>
                      <em className={tone}>{state}</em>
                    </div>
                  ))}
                </div>
                <p className="safe-note"><CircleDot size={13} /> Safeguard configuration shown; runtime health awaits backend verification.</p>
              </motion.article>

              <motion.article className="panel activity" variants={pageMotion} initial="hidden" animate="visible" custom={6}>
                <div className="panel-head"><div><label>03 / EVENT STREAM</label><h2>Recent activity</h2></div><span className="stream"><i /> NO STREAM</span></div>
                <div className="empty"><Radio size={20} /><b>Waiting for verified events</b><p>System activity appears here after backend connection is configured.</p></div>
              </motion.article>
            </div>
          </section>

          <section className="bottom">
            <motion.article className="panel" variants={pageMotion} initial="hidden" animate="visible" custom={7}>
              <div className="panel-head"><div><label>04 / ENVIRONMENT</label><h2>Connected surface</h2></div><Globe2 size={17} /></div>
              <div className="empty-inline"><Boxes size={18} /><b>No authorized assets loaded</b><small>Register and authorize assets before discovery.</small></div>
            </motion.article>
            <motion.article className="panel" variants={pageMotion} initial="hidden" animate="visible" custom={8}>
              <div className="panel-head"><div><label>05 / INTELLIGENCE</label><h2>Relationship graph</h2></div><Network size={17} /></div>
              <div className="empty-inline"><Layers3 size={18} /><b>Graph is not populated</b><small>Verified entities and relationships will render here.</small></div>
            </motion.article>
          </section>

          <footer><b>CYVANTA</b> SECURITY OPERATIONS PLATFORM <span>AUTHORIZED ENVIRONMENTS ONLY &nbsp; • &nbsp; CONTROL & ACCOUNTABILITY</span></footer>
        </div> : <WorkspacePage active={active} />}
      </main>

      <AnimatePresence>
        {searchOpen && <motion.div className="modal-bg" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setSearchOpen(false)}>
          <motion.div className="search-modal" initial={{ y: 12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 12, opacity: 0 }} onClick={(event) => event.stopPropagation()}>
            <div><Command size={16} /> QUICK SEARCH <button onClick={() => setSearchOpen(false)} aria-label="Close search"><X size={17} /></button></div>
            <section><Search size={18} /><input autoFocus placeholder="Search assets, authorizations, evidence..." /></section>
            <p>Search will connect to CYVANTA data services in a later integration step.</p>
          </motion.div>
        </motion.div>}
      </AnimatePresence>

      <AnimatePresence>
        {noticeOpen && <motion.div className="notice" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
          <b>Notifications</b><p>No verified notifications have been received.</p><button onClick={() => setNoticeOpen(false)}>Close</button>
        </motion.div>}
      </AnimatePresence>
    </div>
  );
}

function App() {
  return <AuthGate><Dashboard /></AuthGate>;
}

export default App;
