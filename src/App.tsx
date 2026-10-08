import { useEffect, useMemo, useState } from "react";
import { cases } from "./data";
import type { ClaimCase, Decision } from "./types";

type View = "overview" | "queue" | "case" | "network" | "governance";
type IconName = "grid" | "queue" | "network" | "shield" | "search" | "bell" | "arrow" | "spark" | "check" | "file" | "clock" | "link" | "brain" | "close" | "database" | "person";

const iconPaths: Record<IconName, React.ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
  queue: <><path d="M4 6h16M4 12h16M4 18h10"/><circle cx="19" cy="18" r="2"/></>,
  network: <><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="m10.8 7.2-4.4 8.6m6.8-8.6 4.4 8.6M7.5 18h9"/></>,
  shield: <path d="M12 3 4.5 6v5.2c0 4.7 3.2 8.1 7.5 9.8 4.3-1.7 7.5-5.1 7.5-9.8V6L12 3Zm-3 9 2 2 4-5"/>,
  search: <><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></>,
  bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M10 20h4"/></>,
  arrow: <path d="m9 18 6-6-6-6"/>,
  spark: <><path d="m12 2 1.6 5.4L19 9l-5.4 1.6L12 16l-1.6-5.4L5 9l5.4-1.6L12 2Z"/><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  file: <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/></>,
  link: <><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1-1"/></>,
  brain: <><path d="M9.5 4A3.5 3.5 0 0 0 6 7.5v.7A3.5 3.5 0 0 0 4 11.4 3.5 3.5 0 0 0 7.5 15H9V4h.5ZM14.5 4A3.5 3.5 0 0 1 18 7.5v.7a3.5 3.5 0 0 1 2 3.2 3.5 3.5 0 0 1-3.5 3.6H15V4h-.5Z"/><path d="M9 14v3a3 3 0 0 0 6 0v-3"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></>,
  person: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
};

function Icon({ name, size = 19 }: { name: IconName; size?: number }) {
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{iconPaths[name]}</svg>;
}

const money = (value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);

function Logo() {
  return <div className="logo"><span className="logo-mark"><span /></span><strong>SpotZ<sup>i</sup></strong></div>;
}

function Sidebar({ view, onNavigate }: { view: View; onNavigate: (v: View) => void }) {
  const items: { id: View; label: string; icon: IconName }[] = [
    { id: "overview", label: "Overview", icon: "grid" },
    { id: "queue", label: "SIU queue", icon: "queue" },
    { id: "network", label: "Network explorer", icon: "network" },
    { id: "governance", label: "Governance", icon: "shield" },
  ];
  return <aside className="sidebar">
    <Logo />
    <nav>
      <p className="nav-label">WORKSPACE</p>
      {items.map(item => <button key={item.id} className={view === item.id || (view === "case" && item.id === "queue") ? "nav-item active" : "nav-item"} onClick={() => onNavigate(item.id)}><Icon name={item.icon}/><span>{item.label}</span>{item.id === "queue" && <b>12</b>}</button>)}
    </nav>
    <div className="sidebar-status">
      <div className="status-title"><span className="pulse"/> Analysis current</div>
      <p>RUN-SYN-001</p>
      <small>As of Aug 31, 2025</small>
    </div>
    <div className="profile"><div className="avatar">AM</div><div><strong>Alex Morgan</strong><span>SIU investigator</span></div><button>•••</button></div>
  </aside>;
}

function Topbar({ title, subtitle }: { title: string; subtitle: string }) {
  return <header className="topbar"><div><h1>{title}</h1><p>{subtitle}</p></div><div className="top-actions"><div className="search"><Icon name="search" size={17}/><input aria-label="Search" placeholder="Search cases or providers"/><kbd>⌘K</kbd></div><button className="icon-button"><Icon name="bell"/><span className="notification"/></button></div></header>;
}

function ScoreRing({ value, label, small = false }: { value: number; label?: string; small?: boolean }) {
  return <div className={small ? "score-ring small" : "score-ring"} style={{ "--score": value } as React.CSSProperties}><div><strong>{value}</strong>{label && <span>{label}</span>}</div></div>;
}

function TrendChart() {
  const bars = [34, 48, 42, 58, 51, 66, 72, 61, 77, 70, 84, 92];
  return <div className="trend-wrap"><div className="chart-grid"><span>$300k</span><span>$200k</span><span>$100k</span><span>$0</span></div><div className="bar-chart">{bars.map((h, i) => <div key={i} className={i > 8 ? "bar hot" : "bar"} style={{ height: `${h}%` }}><i>{i > 8 ? money([212000,248000,281000][i-9]) : ""}</i></div>)}</div><div className="chart-labels"><span>Sep</span><span>Nov</span><span>Jan</span><span>Mar</span><span>May</span><span>Jul</span><span>Aug</span></div></div>;
}

function Overview({ openCase, openQueue }: { openCase: (c: ClaimCase) => void; openQueue: () => void }) {
  return <>
    <Topbar title="Good morning, Alex" subtitle="Here’s what needs your attention across the synthetic claims portfolio."/>
    <main className="content">
      <div className="synthetic-banner"><Icon name="database"/><div><strong>Synthetic demonstration environment</strong><span>100,000 claim lines · 5,000 fictional members · 8 service families</span></div><button>Dataset details <Icon name="arrow" size={15}/></button></div>
      <section className="metric-grid">
        <article className="metric-card"><div className="metric-icon teal"><Icon name="queue"/></div><span>Open cases</span><strong>12</strong><small><b>+3</b> since last run</small></article>
        <article className="metric-card"><div className="metric-icon orange"><Icon name="shield"/></div><span>Gross exposure</span><strong>$691K</strong><small>Across 264 distinct lines</small></article>
        <article className="metric-card"><div className="metric-icon purple"><Icon name="person"/></div><span>Members affected</span><strong>158</strong><small>No member culpability inferred</small></article>
        <article className="metric-card"><div className="metric-icon blue"><Icon name="clock"/></div><span>Review capacity</span><strong>31h</strong><small><b>69%</b> available this week</small></article>
      </section>
      <section className="dashboard-grid">
        <article className="panel exposure-panel"><div className="panel-head"><div><span className="eyebrow">PORTFOLIO TREND</span><h2>Implicated paid exposure</h2></div><button className="soft-button">Last 12 months⌄</button></div><TrendChart/><p className="chart-note"><span/> Review scope only — not confirmed recovery</p></article>
        <article className="panel attention-panel"><div className="panel-head"><div><span className="eyebrow">PRIORITY</span><h2>Needs attention</h2></div><button className="text-button" onClick={openQueue}>View queue <Icon name="arrow" size={15}/></button></div>
          {cases.slice(0,3).map(c => <button className="attention-row" key={c.id} onClick={() => openCase(c)}><ScoreRing value={c.priority} small/><div><strong>{c.provider}</strong><span>{c.category}</span><small>{money(c.exposure)} · {c.members} members</small></div><Icon name="arrow" size={17}/></button>)}
        </article>
        <article className="panel signals-panel"><div className="panel-head"><div><span className="eyebrow">SIGNAL MIX</span><h2>How cases were surfaced</h2></div></div>
          <div className="donut-area"><div className="donut"><div><strong>48</strong><span>findings</span></div></div><div className="legend"><span><i className="teal-bg"/>Rules <b>42%</b></span><span><i className="orange-bg"/>Anomaly <b>27%</b></span><span><i className="purple-bg"/>Network <b>19%</b></span><span><i className="blue-bg"/>Temporal <b>12%</b></span></div></div>
        </article>
        <article className="panel challenge-preview"><div className="spark-badge"><Icon name="spark"/></div><div><span className="eyebrow">SPOTZ<sup>i</sup> DIFFERENTIATOR</span><h2>Challenge the evidence</h2><p>Test suspicious patterns against legitimate explanations before a human decides.</p><button className="primary-button" onClick={() => openCase(cases[0])}>Open Evidence Challenge <Icon name="arrow" size={16}/></button></div></article>
      </section>
    </main>
  </>;
}

function Queue({ openCase }: { openCase: (c: ClaimCase) => void }) {
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState("All families");
  const filtered = cases.filter(c => (family === "All families" || c.family === family) && `${c.provider} ${c.category} ${c.id}`.toLowerCase().includes(query.toLowerCase()));
  return <><Topbar title="SIU case queue" subtitle="Ranked recommendations for human review — no automated decisions."/><main className="content">
    <div className="queue-summary"><div><span>Recommended this week</span><strong>7 cases</strong><small>29 of 40 hours</small></div><div className="capacity-bar"><i style={{width:"72%"}}/></div><button className="primary-button">Plan capacity</button></div>
    <div className="filter-row"><div className="filter-search"><Icon name="search" size={17}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Filter queue"/></div><select value={family} onChange={e=>setFamily(e.target.value)}><option>All families</option><option>Laboratory</option><option>DME</option><option>Behavioral health</option><option>Professional</option></select><button className="soft-button">Risk: All</button><button className="soft-button">Status: Active</button><span>{filtered.length} cases</span></div>
    <div className="table-card"><table><thead><tr><th>Priority</th><th>Case & provider</th><th>Category</th><th>Exposure</th><th>Members</th><th>Evidence</th><th>Status</th><th></th></tr></thead><tbody>{filtered.map(c=><tr key={c.id} onClick={()=>openCase(c)}><td><ScoreRing value={c.priority} small/></td><td><strong>{c.provider}</strong><span>{c.id} · {c.specialty}</span></td><td>{c.category}<span>{c.family}</span></td><td><strong>{money(c.exposure)}</strong><span>gross implicated</span></td><td>{c.members}</td><td><div className="quality"><i style={{width:`${c.evidenceQuality}%`}}/></div><span>{c.evidenceQuality}% quality</span></td><td><span className={`status ${c.status.toLowerCase().replaceAll(" ","-")}`}>{c.status}</span></td><td><Icon name="arrow" size={17}/></td></tr>)}</tbody></table></div>
  </main></>;
}

function NetworkView() {
  return <><Topbar title="Network explorer" subtitle="Trace supported relationships across the current synthetic analysis run."/><main className="content"><div className="network-layout"><aside className="network-list"><span className="eyebrow">ACTIVE NETWORKS</span><h2>12 candidate groups</h2>{cases.map((c,i)=><div className={i===0?"network-list-item active":"network-list-item"} key={c.id}><span>{i+1}</span><div><strong>{c.provider}</strong><small>{c.network.length} connected entities</small></div></div>)}</aside><div className="network-canvas"><div className="canvas-toolbar"><span>Northstar referral network</span><div><button>2 hops</button><button>All relationships</button></div></div><div className="graph-stage"><svg viewBox="0 0 760 490" className="graph-lines"><path d="M380 245 170 120M380 245 605 115M380 245 625 360M380 245 160 370"/><path className="dashed" d="M170 120 605 115"/></svg><div className="graph-node hero" style={{left:"43%",top:"41%"}}><b>ND</b><strong>Northstar</strong><span>Laboratory</span></div><div className="graph-node signal" style={{left:"15%",top:"12%"}}><b>HF</b><strong>Harbor Family</strong><span>62% referrals</span></div><div className="graph-node org" style={{left:"72%",top:"11%"}}><b>03</b><strong>SYN-ORG-003</strong><span>Ownership assertion</span></div><div className="graph-node neutral" style={{left:"75%",top:"66%"}}><b>47</b><strong>Members</strong><span>Affected population</span></div><div className="graph-node neutral" style={{left:"13%",top:"69%"}}><b>PM</b><strong>Pioneer Medical</strong><span>19% referrals</span></div></div><div className="graph-legend"><span><i className="primary-dot"/>Primary entity</span><span><i className="signal-dot"/>Evidenced signal</span><span><i className="assertion-line"/>Unverified assertion</span></div></div></div></main></>;
}

function Governance({ decisions }: { decisions: Decision[] }) {
  return <><Topbar title="Governance & audit" subtitle="Every recommendation, reveal, and decision remains reconstructable."/><main className="content"><div className="governance-grid"><article className="governance-hero"><div className="shield-large"><Icon name="shield" size={34}/></div><div><span className="eyebrow">CONTROL STATUS</span><h2>Human decision boundary enforced</h2><p>Analysis services can create recommendations. Only an authenticated reviewer can record an outcome.</p></div><span className="verified"><Icon name="check" size={15}/> Verified</span></article><article className="control-card"><Icon name="database"/><strong>Synthetic-only data</strong><p>Dataset SYN-DEMO-001<br/>Manifest verified</p></article><article className="control-card"><Icon name="person"/><strong>Human approvals</strong><p>{decisions.length} recorded decisions<br/>0 automated outcomes</p></article><article className="control-card"><Icon name="file"/><strong>Evidence lineage</strong><p>100% findings linked<br/>Ruleset v1.0</p></article></div><div className="panel audit-panel"><div className="panel-head"><div><span className="eyebrow">AUDIT TRAIL</span><h2>Recent human activity</h2></div></div>{decisions.length===0?<div className="empty-state"><Icon name="shield" size={30}/><strong>No final decisions recorded yet</strong><p>Open a case, challenge its evidence, and record a human outcome.</p></div>:decisions.map(d=><div className="audit-row" key={`${d.caseId}-${d.decidedAt}`}><div className="audit-icon"><Icon name="check"/></div><div><strong>{d.reviewer} recorded “{d.outcome}”</strong><span>{d.caseId} · {d.reason}</span></div><time>{new Date(d.decidedAt).toLocaleString()}</time></div>)}</div></main></>;
}

function CaseWorkspace({ item, onBack, onDecision }: { item: ClaimCase; onBack: () => void; onDecision: (d: Decision) => void }) {
  const [tab, setTab] = useState<"evidence"|"network"|"forecast"|"activity">("evidence");
  const [challenge, setChallenge] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [outcome, setOutcome] = useState("Inconclusive");
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState(false);
  const submit = () => { if (reason.trim().length < 12) return; onDecision({caseId:item.id,outcome,reason:reason.trim(),reviewer:"Alex Morgan",decidedAt:new Date().toISOString()}); setSaved(true); setDecisionOpen(false); };
  return <><header className="case-top"><button className="back-button" onClick={onBack}>← Queue</button><div className="case-id"><span>{item.id}</span><span className={`severity ${item.severity.toLowerCase()}`}>{item.severity} priority</span><span className="status candidate">{saved?"Human decision recorded":item.status}</span></div><div><button className="soft-button" onClick={()=>setDecisionOpen(true)}><Icon name="person" size={16}/> Record decision</button><button className="primary-button challenge-button" onClick={()=>setChallenge(true)}><Icon name="spark" size={16}/> Challenge evidence</button></div></header><main className="case-content">
    <section className="case-header"><div><span className="eyebrow">{item.specialty.toUpperCase()}</span><h1>{item.provider}</h1><p>{item.summary}</p><div className="case-meta"><span><Icon name="file" size={15}/> Run SYN-001</span><span><Icon name="clock" size={15}/> {item.age} days in queue</span><span><Icon name="person" size={15}/> {item.members} members</span></div></div><div className="case-score"><ScoreRing value={item.risk} label="risk index"/><p>Review recommendation<br/><b>Evidence quality {item.evidenceQuality}%</b></p></div><div className="exposure-stat"><span>Gross implicated exposure</span><strong>{money(item.exposure)}</strong><small>Review scope · not confirmed recovery</small></div></section>
    <nav className="case-tabs">{(["evidence","network","forecast","activity"] as const).map(t=><button key={t} className={tab===t?"active":""} onClick={()=>setTab(t)}>{t[0].toUpperCase()+t.slice(1)}{t==="evidence"&&<b>{item.evidence.length}</b>}</button>)}</nav>
    {tab === "evidence" && <div className="case-grid"><section className="case-main"><div className="section-head"><div><span className="eyebrow">OBSERVED EVIDENCE</span><h2>Why this case was surfaced</h2></div><span className="source-badge"><Icon name="link" size={14}/> Source linked</span></div>{item.evidence.map((ev,i)=><article className="evidence-card" key={ev.id}><div className={`evidence-number ${ev.strength.toLowerCase()}`}>{i+1}</div><div><div className="evidence-title"><strong>{ev.label}</strong><span className={`strength ${ev.strength.toLowerCase()}`}>{ev.strength}</span></div><p>{ev.detail}</p><button><Icon name="file" size={14}/> {ev.source}</button></div></article>)}</section><aside className="case-aside"><div className="challenge-callout"><div className="spark-badge"><Icon name="spark"/></div><span className="eyebrow">EVIDENCE CHALLENGE</span><h3>Could something else explain this?</h3><p>Compare the concern with legitimate alternatives and inspect the evidence most likely to resolve uncertainty.</p><button className="primary-button" onClick={()=>setChallenge(true)}>Challenge this case <Icon name="arrow" size={16}/></button></div><div className="review-checklist"><h3>Human review checklist</h3><span><Icon name="check" size={15}/> Claim lineage reconciled</span><span><Icon name="check" size={15}/> Reversals excluded</span><span className="pending"><i/> Alternative explanation unresolved</span><span className="pending"><i/> Human outcome pending</span></div></aside></div>}
    {tab === "network" && <div className="case-tab-panel"><div className="section-head"><div><span className="eyebrow">RELATIONSHIP CONTEXT</span><h2>Connected synthetic entities</h2></div></div><div className="mini-network">{item.network.map((n,i)=><div className={`entity-card ${n.tone}`} key={n.name}><span>{i+1}</span><div><strong>{n.name}</strong><small>{n.role}</small></div>{i===0&&<b>PRIMARY</b>}</div>)}</div><p className="limitation"><Icon name="shield" size={16}/> Connections provide context. They do not establish responsibility or intent.</p></div>}
    {tab === "forecast" && <div className="case-tab-panel"><div className="section-head"><div><span className="eyebrow">FUTURE ACTIVITY</span><h2>Repeat-event forecast</h2></div><span className="source-badge">Synthetic validation only</span></div><p className="forecast-copy">Estimated probability of a new qualifying repeat event, given information available at the analysis cutoff.</p><div className="forecast-cards">{([30,60,90] as const).map(h=><div className="forecast-card" key={h}><span>By day {h}</span><strong>{item.forecasts[h]}%</strong><div><i style={{width:`${item.forecasts[h]}%`}}/></div><small>Model FCAST-v1 · eligible</small></div>)}</div><p className="limitation"><Icon name="brain" size={16}/> A forecast informs review order. It does not determine the human outcome.</p></div>}
    {tab === "activity" && <div className="case-tab-panel"><div className="section-head"><div><span className="eyebrow">DECISION HISTORY</span><h2>Case activity</h2></div></div><div className="timeline"><div><i/><span>Analysis recommendation created</span><small>RUN-SYN-001 · Rules, anomaly and graph evidence</small></div>{revealed&&<div><i/><span>Human-approved evidence check completed</span><small>{item.check.title}</small></div>}{saved&&<div><i/><span>Human outcome recorded</span><small>{outcome} · Alex Morgan</small></div>}</div></div>}
  </main>
  {challenge && <div className="drawer-backdrop" onMouseDown={e=>{if(e.currentTarget===e.target)setChallenge(false)}}><aside className="challenge-drawer"><div className="drawer-head"><div className="spark-badge"><Icon name="spark"/></div><div><span className="eyebrow">NEXUS EVIDENCE CHALLENGE</span><h2>What else could explain this?</h2></div><button className="icon-button" onClick={()=>setChallenge(false)}><Icon name="close"/></button></div><p className="drawer-intro">Current claims cannot fully distinguish these explanations. Review the alternatives before deciding.</p><div className="explanation-list">{item.explanations.map(ex=><article key={ex.title}><div className="explanation-head"><span className={`kind ${ex.kind.toLowerCase()}`}>{ex.kind}</span><strong>{ex.title}</strong><b>{ex.support}/100</b></div><p>{ex.summary}</p><div><i style={{width:`${ex.support}%`}}/></div></article>)}</div><section className="next-check"><span className="eyebrow">RECOMMENDED NEXT CHECK</span><h3>{item.check.title}</h3><p>{item.check.reason}</p><div><span><Icon name="clock" size={15}/> {item.check.minutes} min review</span><span><Icon name="shield" size={15}/> Can confirm or clear</span></div>{!revealed?<button className="primary-button" onClick={()=>setRevealed(true)}><Icon name="person" size={16}/> Approve & reveal synthetic evidence</button>:<div className="reveal-result"><div className="result-title"><Icon name="check"/><strong>Evidence revealed after human approval</strong></div><p>{item.check.result}</p><span>{item.check.impact}</span><button className="primary-button" onClick={()=>{setChallenge(false);setDecisionOpen(true)}}>Continue to human decision <Icon name="arrow" size={16}/></button></div>}</section><p className="drawer-foot"><Icon name="shield" size={14}/> The evidence was fixed when the synthetic dataset was generated.</p></aside></div>}
  {decisionOpen && <div className="modal-backdrop"><div className="decision-modal"><div className="drawer-head"><div><span className="eyebrow">HUMAN DECISION</span><h2>Record your assessment</h2></div><button className="icon-button" onClick={()=>setDecisionOpen(false)}><Icon name="close"/></button></div><div className="decision-note"><Icon name="person"/><p>You are deciding as <strong>Alex Morgan</strong>. The system cannot submit this decision.</p></div><label>Outcome<select value={outcome} onChange={e=>setOutcome(e.target.value)}><option>Inconclusive</option><option>Needs more information</option><option>Not supported</option><option>Supported for further internal review</option></select></label><label>Reason<textarea value={reason} onChange={e=>setReason(e.target.value)} placeholder="Explain the evidence and alternatives you considered…" rows={5}/><small>{reason.trim().length}/12 minimum characters</small></label><div className="modal-actions"><button className="soft-button" onClick={()=>setDecisionOpen(false)}>Cancel</button><button className="primary-button" disabled={reason.trim().length<12} onClick={submit}><Icon name="check" size={16}/> Record human decision</button></div></div></div>}
  </>;
}

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [selected, setSelected] = useState<ClaimCase>(cases[0]);
  const [decisions, setDecisions] = useState<Decision[]>(() => { try { return JSON.parse(localStorage.getItem("spotzi-decisions") || "[]"); } catch { return []; } });
  useEffect(()=>localStorage.setItem("spotzi-decisions",JSON.stringify(decisions)),[decisions]);
  const openCase = (item: ClaimCase) => { setSelected(item); setView("case"); window.scrollTo(0,0); };
  const shell = useMemo(()=>view!=="case",[view]);
  return <div className={shell?"app-shell":"app-shell case-mode"}>{shell&&<Sidebar view={view} onNavigate={setView}/>}<div className="workspace">{view==="overview"&&<Overview openCase={openCase} openQueue={()=>setView("queue")}/>} {view==="queue"&&<Queue openCase={openCase}/>} {view==="network"&&<NetworkView/>} {view==="governance"&&<Governance decisions={decisions}/>} {view==="case"&&<CaseWorkspace item={selected} onBack={()=>setView("queue")} onDecision={d=>setDecisions(prev=>[d,...prev])}/>}</div></div>;
}
