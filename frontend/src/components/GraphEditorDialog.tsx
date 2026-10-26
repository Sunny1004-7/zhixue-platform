import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  GitBranch,
  Link2,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../api';
import type {
  GraphEdge,
  GraphEvidenceBundle,
  GraphNode,
  KnowledgeGraph,
} from '../types';

const relationLabel = {
  prerequisite: '先修',
  contains: '包含',
  application: '应用',
  contrast: '对比',
} as const;

type NodeDraft = {
  label: string;
  node_type: GraphNode['node_type'];
  definition: string;
  key_point: string;
  misconception: string;
  position_x: number;
  position_y: number;
  teacher_evidence_note: string;
};

type EdgeDraft = {
  from_node_id: string;
  to_node_id: string;
  relation: GraphEdge['relation'];
  teacher_evidence_note: string;
};

type Props = {
  graph: KnowledgeGraph;
  initialNodeId?: string | null;
  onClose: () => void;
  onSaved: (graph: KnowledgeGraph, message: string) => void;
};

const emptyNode = (graph: KnowledgeGraph): NodeDraft => ({
  label: '',
  node_type: 'core',
  definition: '',
  key_point: '',
  misconception: '',
  position_x: 220 + (graph.nodes.length % 4) * 180,
  position_y: 170 + Math.floor(graph.nodes.length / 4) * 120,
  teacher_evidence_note: '',
});

const emptyEdge = (graph: KnowledgeGraph): EdgeDraft => ({
  from_node_id: graph.nodes[0]?.id ?? '',
  to_node_id: graph.nodes[1]?.id ?? '',
  relation: 'prerequisite',
  teacher_evidence_note: '',
});

function locatorText(locator: Record<string, unknown> | null) {
  if (!locator) return '';
  const page = locator.page ?? locator.slide ?? locator.line_start ?? locator.paragraph;
  const kind = locator.kind === 'page' ? '第' : locator.kind === 'slide' ? '幻灯片' : '位置';
  return page == null ? '' : `${kind}${page}${locator.kind === 'page' ? '页' : ''}`;
}

function readableError(reason: unknown) {
  if (reason instanceof ApiError && reason.status === 409) {
    return '图谱已被其他操作更新，本次修改没有覆盖新内容。请刷新后再提交。';
  }
  return reason instanceof ApiError ? reason.message : '保存失败，请稍后重试';
}

export default function GraphEditorDialog({ graph, initialNodeId, onClose, onSaved }: Props) {
  const [tab, setTab] = useState<'nodes' | 'edges'>(initialNodeId ? 'nodes' : 'nodes');
  const [selectedId, setSelectedId] = useState<string | null>(initialNodeId ?? graph.nodes[0]?.id ?? null);
  const [creating, setCreating] = useState(graph.nodes.length === 0);
  const [nodeDraft, setNodeDraft] = useState<NodeDraft>(emptyNode(graph));
  const [edgeDraft, setEdgeDraft] = useState<EdgeDraft>(emptyEdge(graph));
  const [evidence, setEvidence] = useState<GraphEvidenceBundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const nodeById = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);

  const selectedNode = tab === 'nodes' && !creating
    ? graph.nodes.find((node) => node.id === selectedId) ?? null
    : null;
  const selectedEdge = tab === 'edges' && !creating
    ? graph.edges.find((edge) => edge.id === selectedId) ?? null
    : null;

  const loadEvidence = async (targetType: 'node' | 'edge', targetId: string) => {
    setEvidence(null);
    try {
      const result = await api.graphEvidence(graph.id, targetType, targetId);
      setEvidence(result);
      const teacherNote = result.links.find((link) => link.source_kind === 'teacher_statement')?.assertion_note ?? '';
      if (targetType === 'node') {
        setNodeDraft((current) => ({ ...current, teacher_evidence_note: teacherNote }));
      } else {
        setEdgeDraft((current) => ({ ...current, teacher_evidence_note: teacherNote }));
      }
    } catch (reason) {
      setError(readableError(reason));
    }
  };

  useEffect(() => {
    setConfirmDelete(false);
    setError('');
    if (creating) {
      setEvidence(null);
      if (tab === 'nodes') setNodeDraft(emptyNode(graph));
      else setEdgeDraft(emptyEdge(graph));
      return;
    }
    if (tab === 'nodes') {
      const node = graph.nodes.find((item) => item.id === selectedId) ?? graph.nodes[0];
      if (!node) {
        setCreating(true);
        return;
      }
      if (node.id !== selectedId) setSelectedId(node.id);
      setNodeDraft({
        label: node.label, node_type: node.node_type, definition: node.definition,
        key_point: node.key_point, misconception: node.misconception,
        position_x: node.position_x, position_y: node.position_y,
        teacher_evidence_note: '',
      });
      void loadEvidence('node', node.id);
    } else {
      const edge = graph.edges.find((item) => item.id === selectedId) ?? graph.edges[0];
      if (!edge) {
        setCreating(true);
        return;
      }
      if (edge.id !== selectedId) setSelectedId(edge.id);
      setEdgeDraft({
        from_node_id: edge.from_node_id, to_node_id: edge.to_node_id,
        relation: edge.relation, teacher_evidence_note: '',
      });
      void loadEvidence('edge', edge.id);
    }
    // selectedId is intentionally the interaction key; loadEvidence uses the current graph revision.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, selectedId, creating, graph.id, graph.version]);

  const refreshAfterConflict = async () => {
    try {
      onSaved(await api.teacherGraph(graph.id), '已刷新到最新图谱内容');
    } catch (reason) {
      setError(readableError(reason));
    }
  };

  const saveNode = async () => {
    if (!nodeDraft.label.trim()) return;
    setBusy(true); setError('');
    try {
      const payload = {
        ...nodeDraft,
        label: nodeDraft.label.trim(),
        expected_revision_version: graph.version,
      };
      const result = selectedNode
        ? await api.updateGraphNode(graph.id, selectedNode.id, payload)
        : await api.addGraphNode(graph.id, payload);
      const selected = selectedNode?.id
        ?? result.nodes.find((node) => node.label === payload.label)?.id
        ?? result.nodes.at(-1)?.id
        ?? null;
      setCreating(false); setSelectedId(selected);
      onSaved(result, selectedNode ? '知识点修改已保存' : '知识点已加入图谱');
    } catch (reason) {
      setError(readableError(reason));
      if (reason instanceof ApiError && reason.status === 409) await refreshAfterConflict();
    } finally {
      setBusy(false);
    }
  };

  const saveEdge = async () => {
    if (!edgeDraft.from_node_id || !edgeDraft.to_node_id || edgeDraft.from_node_id === edgeDraft.to_node_id) return;
    setBusy(true); setError('');
    try {
      const payload = { ...edgeDraft, expected_revision_version: graph.version };
      const result = selectedEdge
        ? await api.updateGraphEdge(graph.id, selectedEdge.id, payload)
        : await api.addGraphEdge(graph.id, payload);
      const selected = selectedEdge?.id
        ?? result.edges.find((edge) => edge.from_node_id === payload.from_node_id
          && edge.to_node_id === payload.to_node_id && edge.relation === payload.relation)?.id
        ?? result.edges.at(-1)?.id
        ?? null;
      setCreating(false); setSelectedId(selected);
      onSaved(result, selectedEdge ? '关系修改已保存' : '关系已加入图谱');
    } catch (reason) {
      setError(readableError(reason));
      if (reason instanceof ApiError && reason.status === 409) await refreshAfterConflict();
    } finally {
      setBusy(false);
    }
  };

  const removeSelected = async () => {
    if (!selectedId) return;
    setBusy(true); setError('');
    try {
      const result = tab === 'nodes'
        ? await api.deleteGraphNode(graph.id, selectedId, graph.version)
        : await api.deleteGraphEdge(graph.id, selectedId, graph.version);
      const nextId = tab === 'nodes' ? result.nodes[0]?.id : result.edges[0]?.id;
      setSelectedId(nextId ?? null); setCreating(!nextId); setConfirmDelete(false);
      onSaved(result, tab === 'nodes' ? '知识点及其关联关系已删除' : '关系已删除');
    } catch (reason) {
      setError(readableError(reason));
      if (reason instanceof ApiError && reason.status === 409) await refreshAfterConflict();
    } finally {
      setBusy(false);
    }
  };

  const switchTab = (next: 'nodes' | 'edges') => {
    setTab(next); setCreating(next === 'nodes' ? graph.nodes.length === 0 : graph.edges.length === 0);
    setSelectedId(next === 'nodes' ? graph.nodes[0]?.id ?? null : graph.edges[0]?.id ?? null);
  };

  const startCreate = () => {
    setCreating(true); setSelectedId(null); setConfirmDelete(false); setError('');
  };

  return <div className="dialog-backdrop graph-editor-backdrop" role="presentation">
    <section className="graph-editor-dialog" role="dialog" aria-modal="true" aria-label="编辑知识图谱">
      <header className="graph-editor-header">
        <div><span><GitBranch size={15} />图谱编辑器</span><h3>{graph.title}</h3></div>
        <div className="graph-editor-header-meta"><em>修订 {graph.revision_no}</em><b>内容版本 {graph.version}</b><button aria-label="关闭图谱编辑器" onClick={onClose}><X size={18} /></button></div>
      </header>
      <div className="graph-editor-tabs">
        <button className={tab === 'nodes' ? 'active' : ''} onClick={() => switchTab('nodes')}><FileText size={15} />知识点 <span>{graph.nodes.length}</span></button>
        <button className={tab === 'edges' ? 'active' : ''} onClick={() => switchTab('edges')}><Link2 size={15} />知识关系 <span>{graph.edges.length}</span></button>
      </div>
      {error && <div className="graph-editor-error"><AlertTriangle size={15} />{error}</div>}
      <div className="graph-editor-body">
        <aside className="graph-editor-list">
          <button className="graph-editor-add" onClick={startCreate} disabled={tab === 'edges' && graph.nodes.length < 2}><Plus size={15} />{tab === 'nodes' ? '新增知识点' : '新增关系'}</button>
          <div>
            {tab === 'nodes' ? graph.nodes.map((node) => <button key={node.id} className={!creating && selectedId === node.id ? 'active' : ''} onClick={() => { setCreating(false); setSelectedId(node.id); }}>
              <span className={`node-dot ${node.node_type}`} /><div><b>{node.label}</b><small>{node.node_type === 'foundation' ? '基础' : node.node_type === 'application' ? '应用' : '核心'} · {node.evidence_count || (node.origin === 'curated_seed' ? 1 : 0)}项来源</small></div>
            </button>) : graph.edges.map((edge) => <button key={edge.id} className={!creating && selectedId === edge.id ? 'active' : ''} onClick={() => { setCreating(false); setSelectedId(edge.id); }}>
              <Link2 size={14} /><div><b>{nodeById.get(edge.from_node_id)?.label} → {nodeById.get(edge.to_node_id)?.label}</b><small>{relationLabel[edge.relation]} · {edge.evidence_count || (edge.origin === 'curated_seed' ? 1 : 0)}项来源</small></div>
            </button>)}
          </div>
        </aside>
        <main className="graph-editor-main">
          <div className="graph-editor-form-title">
            <div><small>{creating ? '新建' : '编辑'}</small><h4>{tab === 'nodes' ? (creating ? '新增知识点' : selectedNode?.label) : (creating ? '新增知识关系' : `${nodeById.get(selectedEdge?.from_node_id ?? '')?.label} → ${nodeById.get(selectedEdge?.to_node_id ?? '')?.label}`)}</h4></div>
            {!creating && <div className="graph-delete-actions">{confirmDelete
              ? <><button onClick={() => setConfirmDelete(false)}>取消</button><button className="danger" disabled={busy} onClick={() => void removeSelected()}><Trash2 size={14} />确认删除</button></>
              : <button className="delete" onClick={() => setConfirmDelete(true)}><Trash2 size={14} />删除</button>}</div>}
          </div>
          {tab === 'nodes' ? <div className="graph-node-editor-form">
            <div className="graph-editor-grid two">
              <label><span>知识点名称</span><input value={nodeDraft.label} onChange={(event) => setNodeDraft({ ...nodeDraft, label: event.target.value })} placeholder="例如：偏差与方差" /></label>
              <label><span>知识点类型</span><select value={nodeDraft.node_type} onChange={(event) => setNodeDraft({ ...nodeDraft, node_type: event.target.value as GraphNode['node_type'] })}><option value="foundation">基础</option><option value="core">核心</option><option value="application">应用</option></select></label>
            </div>
            <label><span>定义</span><textarea value={nodeDraft.definition} onChange={(event) => setNodeDraft({ ...nodeDraft, definition: event.target.value })} placeholder="给出适合课程语境的准确解释" /></label>
            <div className="graph-editor-grid two">
              <label><span>学习要点</span><textarea value={nodeDraft.key_point} onChange={(event) => setNodeDraft({ ...nodeDraft, key_point: event.target.value })} placeholder="学生需要抓住的核心" /></label>
              <label><span>常见误区</span><textarea value={nodeDraft.misconception} onChange={(event) => setNodeDraft({ ...nodeDraft, misconception: event.target.value })} placeholder="容易混淆或误用之处" /></label>
            </div>
            <div className="graph-editor-grid coordinates">
              <label><span>横向位置</span><input type="number" min="0" max="2000" value={nodeDraft.position_x} onChange={(event) => setNodeDraft({ ...nodeDraft, position_x: Number(event.target.value) })} /></label>
              <label><span>纵向位置</span><input type="number" min="0" max="1200" value={nodeDraft.position_y} onChange={(event) => setNodeDraft({ ...nodeDraft, position_y: Number(event.target.value) })} /></label>
              <div><span>布局坐标</span><small>保存后立即更新图谱位置</small></div>
            </div>
            <label><span>教师来源说明（可选）</span><textarea value={nodeDraft.teacher_evidence_note} onChange={(event) => setNodeDraft({ ...nodeDraft, teacher_evidence_note: event.target.value })} placeholder="用于记录无法由材料原文覆盖的教学判断" /></label>
          </div> : <div className="graph-edge-editor-form">
            {graph.nodes.length < 2 ? <div className="graph-editor-empty"><AlertTriangle size={22} /><b>至少需要两个知识点</b><span>请先在“知识点”页签中补充节点。</span></div> : <>
              <div className="graph-editor-grid two">
                <label><span>起点知识点</span><select value={edgeDraft.from_node_id} onChange={(event) => setEdgeDraft({ ...edgeDraft, from_node_id: event.target.value })}>{graph.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
                <label><span>终点知识点</span><select value={edgeDraft.to_node_id} onChange={(event) => setEdgeDraft({ ...edgeDraft, to_node_id: event.target.value })}>{graph.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select></label>
              </div>
              {edgeDraft.from_node_id === edgeDraft.to_node_id && <div className="graph-editor-warning"><AlertTriangle size={14} />关系不能连接知识点自身</div>}
              <label><span>关系类型</span><select value={edgeDraft.relation} onChange={(event) => setEdgeDraft({ ...edgeDraft, relation: event.target.value as GraphEdge['relation'] })}>{Object.entries(relationLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label><span>教师来源说明（可选）</span><textarea value={edgeDraft.teacher_evidence_note} onChange={(event) => setEdgeDraft({ ...edgeDraft, teacher_evidence_note: event.target.value })} placeholder="说明该关系在本课程教学结构中的依据" /></label>
              <div className="edge-preview"><span>{nodeById.get(edgeDraft.from_node_id)?.label || '起点'}</span><b>{relationLabel[edgeDraft.relation]}</b><span>{nodeById.get(edgeDraft.to_node_id)?.label || '终点'}</span></div>
            </>}
          </div>}
          {!creating && <section className="graph-evidence-panel">
            <header><div><FileText size={15} /><b>来源证据</b></div>{!evidence && <RefreshCw size={14} className="spin" />}</header>
            {evidence && evidence.links.length === 0 && <div className="graph-evidence-empty"><AlertTriangle size={17} /><span>尚未绑定材料证据或教师来源说明</span></div>}
            {evidence?.links.map((link) => <article key={link.id}>
              <div><span className={link.source_kind}>{link.source_kind === 'material_span' ? '材料原文' : link.source_kind === 'teacher_statement' ? '教师说明' : '课程初始内容'}</span><b>{link.source_name || '当前课程图谱'}</b><em>{locatorText(link.locator)}</em></div>
              {link.quote && <blockquote>{link.quote}</blockquote>}
              {link.assertion_note && <p>{link.assertion_note}</p>}
              <small>{link.source_model_run_id ? `模型运行 ${link.source_model_run_id.slice(0, 8)} · ` : ''}置信度 {Math.round(link.confidence * 100)}%</small>
            </article>)}
          </section>}
        </main>
      </div>
      <footer className="graph-editor-footer">
        <div>{busy ? <span><RefreshCw size={14} className="spin" />正在保存并更新图谱…</span> : <span><CheckCircle2 size={14} />每次修改都会使旧质量审核失效</span>}</div>
        <div><button onClick={onClose}>关闭</button><button className="primary" disabled={busy || (tab === 'nodes' ? !nodeDraft.label.trim() : !edgeDraft.from_node_id || !edgeDraft.to_node_id || edgeDraft.from_node_id === edgeDraft.to_node_id)} onClick={() => void (tab === 'nodes' ? saveNode() : saveEdge())}><Save size={15} />保存{tab === 'nodes' ? '知识点' : '关系'}</button></div>
      </footer>
    </section>
  </div>;
}
