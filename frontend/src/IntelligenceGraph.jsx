import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Activity, AlertTriangle, Database, Maximize2, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { apiRequest } from "./api";

const TYPE_ORDER = [
  "organization", "member", "asset", "authorization", "authorization_event",
  "mission", "action", "approval", "execution", "execution_event",
];

const TYPE_LABELS = {
  organization: "ORGANIZATION",
  member: "MEMBER",
  asset: "ASSET",
  authorization: "AUTHORIZATION",
  authorization_event: "AUTH EVENT",
  mission: "MISSION",
  action: "ACTION",
  approval: "APPROVAL",
  execution: "EXECUTION",
  execution_event: "EXECUTION EVENT",
};

function nodeColor(node) {
  const status = String(node.status || "").toLowerCase();
  if (["rejected", "revoked", "failed", "cancelled", "suspended"].includes(status)) return "#f87171";
  if (["pending", "queued", "approved", "verified", "active"].includes(status)) {
    if (["pending", "queued"].includes(status)) return "#fbbf24";
    return "#39c98a";
  }
  const colors = {
    organization: "#a78bfa", member: "#42b98c", asset: "#45c78e",
    authorization: "#39c98a", authorization_event: "#43b78b",
    mission: "#a78bfa", action: "#fbbf24", approval: "#fbbf24",
    execution: "#f59e0b", execution_event: "#42b98c",
  };
  return colors[node.type] || "#58b99a";
}

function forceLayout(rawNodes, rawEdges) {
  const count = rawNodes.length;
  if (!count) return { nodes: [], edges: [] };

  const indexById = new Map(rawNodes.map((node, index) => [node.id, index]));
  const width = Math.max(760, Math.min(1180, 520 + count * 28));
  const height = Math.max(480, Math.min(760, 390 + count * 18));
  const center = { x: width / 2, y: height / 2 };
  const positions = rawNodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
    const radius = 95 + (index % 3) * 34;
    return {
      x: center.x + Math.cos(angle) * radius,
      y: center.y + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
    };
  });

  const links = rawEdges
    .map((edge) => ({
      source: indexById.get(edge.source),
      target: indexById.get(edge.target),
    }))
    .filter((edge) => edge.source !== undefined && edge.target !== undefined);

  for (let iteration = 0; iteration < 180; iteration += 1) {
    const alpha = 0.72 * (1 - iteration / 200);
    for (let i = 0; i < count; i += 1) {
      for (let j = i + 1; j < count; j += 1) {
        let dx = positions[i].x - positions[j].x;
        let dy = positions[i].y - positions[j].y;
        const distanceSquared = Math.max(36, dx * dx + dy * dy);
        const distance = Math.sqrt(distanceSquared);
        const force = 3000 / distanceSquared;
        dx = (dx / distance) * force;
        dy = (dy / distance) * force;
        positions[i].vx += dx;
        positions[i].vy += dy;
        positions[j].vx -= dx;
        positions[j].vy -= dy;
      }
    }

    links.forEach(({ source, target }) => {
      const dx = positions[target].x - positions[source].x;
      const dy = positions[target].y - positions[source].y;
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const force = (distance - 150) * 0.012;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      positions[source].vx += fx;
      positions[source].vy += fy;
      positions[target].vx -= fx;
      positions[target].vy -= fy;
    });

    positions.forEach((position, index) => {
      const node = rawNodes[index];
      const anchor = node.type === "organization" ? 0.045 : 0.004;
      position.vx += (center.x - position.x) * anchor;
      position.vy += (center.y - position.y) * anchor;
      position.vx *= 0.72;
      position.vy *= 0.72;
      position.x += position.vx * alpha;
      position.y += position.vy * alpha;
    });
  }

  const minX = Math.min(...positions.map((position) => position.x));
  const minY = Math.min(...positions.map((position) => position.y));
  const maxX = Math.max(...positions.map((position) => position.x));
  const maxY = Math.max(...positions.map((position) => position.y));
  const offsetX = Math.max(80, (width - (maxX - minX)) / 2 - minX);
  const offsetY = Math.max(80, (height - (maxY - minY)) / 2 - minY);

  const nodes = rawNodes.map((node, index) => ({
    id: node.id,
    type: "cyvantaDot",
    position: { x: positions[index].x + offsetX, y: positions[index].y + offsetY },
    data: {
      label: node.label || TYPE_LABELS[node.type] || node.type,
      entityType: node.type,
      typeLabel: TYPE_LABELS[node.type] || String(node.type).toUpperCase(),
      status: node.status || "",
      color: nodeColor(node),
      metadata: node.metadata || {},
    },
  }));

  const edges = rawEdges
    .filter((edge) => indexById.has(edge.source) && indexById.has(edge.target))
    .map((edge) => {
      const target = rawNodes[indexById.get(edge.target)];
      const color = ["pending", "queued"].includes(String(target.status || "").toLowerCase())
        ? "rgba(245, 190, 66, .8)"
        : "rgba(54, 187, 137, .58)";
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "default",
        animated: false,
        style: { stroke: color, strokeWidth: 1.35 },
      };
    });

  return { nodes, edges };
}

function GraphDot({ data, selected }) {
  const initials = data.entityType === "organization" ? "ORG"
    : data.entityType === "authorization_event" || data.entityType === "execution_event" ? "EV"
    : data.entityType.slice(0, 2).toUpperCase();

  return (
    <div className={`cyvanta-dot-wrap${selected ? " is-selected" : ""}`} title={`${data.typeLabel}: ${data.label}`}>
      <Handle type="target" position={Position.Left} />
      <div className="cyvanta-dot" style={{ "--dot-color": data.color }}>
        <span>{initials}</span>
      </div>
      <div className="cyvanta-dot-label">{data.label}</div>
      {data.status ? <div className="cyvanta-dot-status">{data.status}</div> : null}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { cyvantaDot: GraphDot };

function Value({ value }) {
  if (value === null || value === undefined || value === "") return <span>—</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value === "object") return <pre>{JSON.stringify(value, null, 2)}</pre>;
  return <span>{String(value)}</span>;
}

export default function IntelligenceGraph() {
  const [payload, setPayload] = useState(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await apiRequest("/intelligence-graph");
      if (!result || !Array.isArray(result.nodes) || !Array.isArray(result.edges)) {
        throw new Error("The graph API returned an unexpected response structure.");
      }
      const layout = forceLayout(result.nodes, result.edges);
      setPayload(result);
      setNodes(layout.nodes);
      setEdges(layout.edges);
      setSelected(null);
    } catch (loadError) {
      setError(loadError?.message || "Unable to load the organization graph.");
      setPayload(null);
      setNodes([]);
      setEdges([]);
      setSelected(null);
    } finally {
      setLoading(false);
    }
  }, [setEdges, setNodes]);

  useEffect(() => { loadGraph(); }, [loadGraph]);

  const selectedNode = useMemo(
    () => selected ? nodes.find((node) => node.id === selected) || null : null,
    [nodes, selected]
  );

  const filteredNodes = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return nodes;
    return nodes.filter((node) =>
      `${node.data.label} ${node.data.typeLabel} ${node.data.status} ${node.id}`.toLowerCase().includes(term)
    );
  }, [nodes, search]);

  const summary = payload?.summary || {};
  const hasGraph = nodes.length > 0;

  const selectNode = (nodeId) => {
    setSelected(nodeId);
    const node = nodes.find((item) => item.id === nodeId);
    if (node) {
      setNodes((current) => current.map((item) => ({
        ...item,
        selected: item.id === nodeId,
      })));
    }
  };

  return (
    <div className="cyvanta-network-app">
      <div className="cyvanta-network-topbar">
        <div className="cyvanta-network-brand"><span className="cyvanta-brand-mark"><Activity size={17}/></span><b>CYVANTA</b><small>INTELLIGENCE NETWORK</small></div>
        <label className="cyvanta-network-search">
          <Search size={15}/>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search nodes, assets, authorizations..." />
          <kbd>FILTER</kbd>
        </label>
        <button className="workspace-refresh cyvanta-network-refresh" onClick={loadGraph} disabled={loading}>
          <RefreshCw size={14}/>{loading ? "Syncing" : "Refresh"}
        </button>
      </div>

      <div className="cyvanta-network-layout">
        <section className="cyvanta-network-canvas">
          <div className="cyvanta-network-canvas-meta">
            <span><i/> LIVE ORGANIZATION DATA</span>
            <span>{summary.nodes ?? nodes.length} NODES <b>·</b> {summary.edges ?? edges.length} LINKS</span>
          </div>

          {error ? (
            <div className="cyvanta-network-empty cyvanta-network-error">
              <AlertTriangle size={22}/><b>Graph unavailable</b><p>{error}</p>
            </div>
          ) : null}

          {!error && loading && !hasGraph ? (
            <div className="cyvanta-network-empty"><RefreshCw size={20}/><b>Loading relationship network</b></div>
          ) : null}

          {!error && !loading && !hasGraph ? (
            <div className="cyvanta-network-empty"><Database size={22}/><b>No graph records returned</b><p>The backend returned no nodes for this organization. No sample entities or relationships are generated.</p></div>
          ) : null}

          {hasGraph ? (
            <div className="cyvanta-network-flow">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={(_, node) => selectNode(node.id)}
                onPaneClick={() => { setSelected(null); setNodes((current) => current.map((node) => ({ ...node, selected: false }))); }}
                fitView
                fitViewOptions={{ padding: 0.22, maxZoom: 1.1 }}
                minZoom={0.12}
                maxZoom={2.2}
                proOptions={{ hideAttribution: true }}
              >
                <Background color="rgba(83, 135, 123, .10)" gap={24} size={1}/>
                <Controls showInteractive={false}/>
                <MiniMap
                  pannable
                  zoomable
                  nodeColor={(node) => node.data?.color || "#39b98a"}
                  maskColor="rgba(4, 10, 19, .76)"
                />
              </ReactFlow>
            </div>
          ) : null}

          <div className="cyvanta-network-legend">
            <span><i className="legend-green"/> VERIFIED / ACTIVE</span>
            <span><i className="legend-yellow"/> PENDING / QUEUED</span>
            <span><i className="legend-red"/> REJECTED / REVOKED</span>
            <span className="cyvanta-network-readonly">READ-ONLY · REAL BACKEND RECORDS</span>
          </div>
        </section>

        <aside className="cyvanta-network-side">
          <div className="cyvanta-side-heading">
            <div><span>NODE EXPLORER</span><small>{filteredNodes.length} OF {nodes.length} RECORDS</small></div>
            <ShieldCheck size={17}/>
          </div>
          <div className="cyvanta-node-list">
            {filteredNodes.map((node) => (
              <button
                type="button"
                key={node.id}
                className={`cyvanta-node-row${selected === node.id ? " active" : ""}`}
                onClick={() => selectNode(node.id)}
              >
                <i style={{ "--dot-color": node.data.color }}/>
                <span><small>{node.data.typeLabel}</small><b>{node.data.label}</b><em>{node.data.status || "No status"}</em></span>
              </button>
            ))}
            {!filteredNodes.length ? <div className="cyvanta-node-no-results">No matching records.</div> : null}
          </div>

          <div className="cyvanta-side-detail">
            <div className="cyvanta-side-heading"><div><span>NODE DETAILS</span></div><Database size={15}/></div>
            {selectedNode ? (
              <>
                <div className="cyvanta-detail-type">{selectedNode.data.typeLabel}</div>
                <h3>{selectedNode.data.label}</h3>
                {selectedNode.data.status ? <span className="cyvanta-detail-status">{selectedNode.data.status}</span> : null}
                <div className="cyvanta-detail-fields">
                  {Object.entries(selectedNode.data.metadata || {}).map(([key, value]) => (
                    <div key={key}><small>{key.replaceAll("_", " ")}</small><Value value={value}/></div>
                  ))}
                </div>
                <code>{selectedNode.id}</code>
              </>
            ) : <div className="cyvanta-detail-empty">Select a node from the network or node explorer to inspect its backend fields.</div>}
          </div>
        </aside>
      </div>
      <div className="cyvanta-network-footer">
        <span>CYVANTA / INTELLIGENCE GRAPH v1</span>
        <span>Graph topology is calculated from returned records; no entities or relationships are fabricated.</span>
      </div>
    </div>
  );
}
