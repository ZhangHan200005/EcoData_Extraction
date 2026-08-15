"use client";

import { useEffect, useMemo, useState } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8771";

type FieldSpec = {
  name: string;
  label: string;
  synonyms: string[];
  canonical_unit?: string;
};

type ProjectSpec = {
  brief: string;
  domain: string;
  target_variables: FieldSpec[];
  required_context: FieldSpec[];
  optional_context: FieldSpec[];
  accepted_sources: string[];
  exclusions: string[];
  interpretation_warnings: string[];
};

type DocumentRecord = {
  document_id: string;
  filename: string;
  title: string;
  publication_year: number | null;
  language: string;
  page_count: number;
  text_char_count: number;
  parser_status: string;
  parser_warnings: string[];
  screening_status: "usable" | "relative" | "nodata" | "failed";
  screening_reasons: string[];
  missing_required_fields: string[];
  block_count: number;
  figure_caption_count: number;
  table_caption_count: number;
  sections: string[];
  covered_fields: string[];
  summary: string;
};

type BlockRecord = {
  block_id: string;
  document_id: string;
  ordinal: number;
  page: number;
  section: string;
  kind: string;
  text: string;
  bbox: number[];
};

type GoldRecord = {
  gold_id: string;
  document_id: string;
  field_name: string;
  block_id: string;
  status: string;
  note: string;
  created_at: string;
};

type RetrievalHit = {
  rank: number;
  block: BlockRecord;
  score: number;
  score_components: Record<string, number>;
  matched_terms: string[];
  is_gold: boolean;
};

type RetrievalBackend = {
  backend: string;
  backend_version: string;
  model: string;
  model_version: string;
  dimensions: number;
  is_neural: boolean;
};

type RetrievalCacheStats = {
  enabled: boolean;
  hits: number;
  misses: number;
  writes: number;
};

type RetrievalResponse = {
  run_id: string;
  field_name: string;
  query: string;
  retrieval_version: string;
  backend: RetrievalBackend;
  parameters: Record<string, unknown>;
  query_count: number;
  total_blocks: number;
  elapsed_ms: number;
  cache: RetrievalCacheStats;
  hits: RetrievalHit[];
};

type RetrievalComparisonMetrics = {
  gold_count: number;
  first_gold_rank: number | null;
  hit_at_k: number | null;
  recall_at_k: number | null;
  reciprocal_rank: number | null;
};

type RetrievalComparisonItem = {
  strategy: "bm25-only" | "hashing-hybrid" | "e5-hybrid";
  label: string;
  status: "available" | "unavailable";
  retrieval: RetrievalResponse | null;
  metrics: RetrievalComparisonMetrics | null;
  error: string;
};

type RetrievalComparison = {
  comparison_id: string;
  document_id: string;
  field_name: string;
  query: string;
  k: number;
  gold_status: "verified";
  items: RetrievalComparisonItem[];
};

type Evaluation = {
  generated_at: string;
  retrieval_version: string;
  backend?: RetrievalBackend;
  parameters?: Record<string, unknown>;
  timing?: Record<string, number>;
  coverage: Record<string, number>;
  metrics_at_k: Record<
    string,
    { hit_rate: number; recall: number; precision: number }
  >;
  mean_reciprocal_rank: number;
  per_field: Array<{
    field_name: string;
    query_count: number;
    gold_count: number;
    mrr: number;
    metrics: Record<
      string,
      { hit: number; recall: number; precision: number }
    >;
  }>;
};

type StatePayload = {
  spec: ProjectSpec | null;
  documents: DocumentRecord[];
  gold: GoldRecord[];
  latest_evaluation: Evaluation | null;
  source_directory: string;
};

const DEFAULT_BRIEF =
  "我希望提取树干呼吸速率数据，必须报告物种和样本量；关注站点、经纬度、胸径、测量温度和测量方法。接受正文、表格和数据图中的观测值或均值，不接受模型预测值。经纬度缺失时可以保留为 relative。";

const STAGES = [
  { id: "brief", step: "01", label: "研究需求" },
  { id: "documents", step: "02", label: "全文解析与筛选" },
  { id: "retrieval", step: "03", label: "证据召回审计" },
  { id: "evaluation", step: "04", label: "量化评估" },
] as const;

type StageId = (typeof STAGES)[number]["id"];

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail ?? body.error ?? response.statusText);
  }
  return body as T;
}

function percent(value: number | undefined) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function statusLabel(status: DocumentRecord["screening_status"]) {
  return (
    {
      usable: "可用",
      relative: "部分相关",
      nodata: "无可提取数据",
      failed: "解析失败",
    } as const
  )[status];
}

function FieldChips({
  title,
  fields,
  tone = "neutral",
}: {
  title: string;
  fields: FieldSpec[];
  tone?: "neutral" | "required" | "target";
}) {
  return (
    <div className="field-group">
      <span className="eyebrow">{title}</span>
      <div className="chip-row">
        {fields.length ? (
          fields.map((field) => (
            <span className={`chip ${tone}`} key={field.name}>
              {field.label}
              {field.canonical_unit ? (
                <small>{field.canonical_unit}</small>
              ) : null}
            </span>
          ))
        ) : (
          <span className="muted">未识别</span>
        )}
      </div>
    </div>
  );
}

export default function Home() {
  const [stage, setStage] = useState<StageId>("brief");
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [state, setState] = useState<StatePayload>({
    spec: null,
    documents: [],
    gold: [],
    latest_evaluation: null,
    source_directory: "",
  });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [selectedField, setSelectedField] = useState("");
  const [topK, setTopK] = useState(8);
  const [retrieval, setRetrieval] =
    useState<RetrievalResponse | null>(null);
  const [comparison, setComparison] =
    useState<RetrievalComparison | null>(null);
  const [blockQuery, setBlockQuery] = useState("");
  const [blockSearch, setBlockSearch] = useState<BlockRecord[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);

  const refresh = async () => {
    const payload = await api<StatePayload>("/api/state");
    setState(payload);
    if (payload.spec) setBrief(payload.spec.brief);
    if (!selectedDocumentId && payload.documents.length) {
      setSelectedDocumentId(payload.documents[0].document_id);
    }
    if (!selectedField && payload.spec) {
      const first =
        payload.spec.target_variables[0] ??
        payload.spec.required_context[0] ??
        payload.spec.optional_context[0];
      if (first) setSelectedField(first.name);
    }
    if (payload.latest_evaluation) {
      setEvaluation(payload.latest_evaluation);
    }
  };

  useEffect(() => {
    let active = true;
    api<StatePayload>("/api/state")
      .then((payload) => {
        if (!active) return;
        setState(payload);
        if (payload.spec) {
          setBrief(payload.spec.brief);
          const first =
            payload.spec.target_variables[0] ??
            payload.spec.required_context[0] ??
            payload.spec.optional_context[0];
          if (first) setSelectedField(first.name);
        }
        if (payload.documents.length) {
          setSelectedDocumentId(payload.documents[0].document_id);
        }
        if (payload.latest_evaluation) {
          setEvaluation(payload.latest_evaluation);
        }
      })
      .catch((reason) => {
        if (active) setError(`后端尚未连接：${reason.message}`);
      });
    return () => {
      active = false;
    };
  }, []);

  const availableFields = useMemo(() => {
    const spec = state.spec;
    if (!spec) return [];
    const fields = [
      ...spec.target_variables,
      ...spec.required_context,
      ...spec.optional_context,
    ];
    return Array.from(
      new Map(fields.map((field) => [field.name, field])).values(),
    );
  }, [state.spec]);

  const statusCounts = useMemo(() => {
    return state.documents.reduce<Record<string, number>>((counts, document) => {
      counts[document.screening_status] =
        (counts[document.screening_status] ?? 0) + 1;
      return counts;
    }, {});
  }, [state.documents]);

  const runAction = async (name: string, action: () => Promise<void>) => {
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  const interpretBrief = () =>
    runAction("interpret", async () => {
      const result = await api<{ spec: ProjectSpec }>(
        "/api/spec/interpret",
        {
          method: "POST",
          body: JSON.stringify({ brief }),
        },
      );
      setState((current) => ({ ...current, spec: result.spec }));
      setNotice("研究需求已拆解并保存。请核对系统理解。");
    });

  const syncDocuments = () =>
    runAction("sync", async () => {
      await api("/api/documents/sync", { method: "POST" });
      await refresh();
      setNotice("演示文献已按 PDF 哈希复用或重新解析。");
    });

  const fetchRetrieval = async () => {
    if (!selectedDocumentId || !selectedField) {
      throw new Error("请选择论文和检索字段。");
    }
    const result = await api<RetrievalResponse>("/api/retrieve", {
      method: "POST",
      body: JSON.stringify({
        document_id: selectedDocumentId,
        field_name: selectedField,
        k: topK,
      }),
    });
    setRetrieval(result);
    return result;
  };

  const runRetrieval = () =>
    runAction("retrieve", async () => {
      const result = await fetchRetrieval();
      setComparison(null);
      setNotice(`已从 ${result.total_blocks} 个全文证据块中返回 Top ${topK}。`);
    });

  const fetchComparison = async () => {
    if (!selectedDocumentId || !selectedField) {
      throw new Error("请选择论文和检索字段。");
    }
    const result = await api<RetrievalComparison>(
      "/api/retrieve/compare",
      {
        method: "POST",
        body: JSON.stringify({
          document_id: selectedDocumentId,
          field_name: selectedField,
          k: topK,
        }),
      },
    );
    setComparison(result);
    const hashing = result.items.find(
      (item) => item.strategy === "hashing-hybrid",
    );
    setRetrieval(hashing?.retrieval ?? null);
    return result;
  };

  const runComparison = () =>
    runAction("compare", async () => {
      const result = await fetchComparison();
      const available = result.items.filter(
        (item) => item.status === "available",
      ).length;
      setNotice(
        `已完成 ${available}/${result.items.length} 种策略的同查询对照；下方保留 hashing 结果用于全文补漏。`,
      );
    });

  const addGold = (block: BlockRecord) =>
    runAction(`gold-${block.block_id}`, async () => {
      await api("/api/gold", {
        method: "POST",
        body: JSON.stringify({
          document_id: block.document_id,
          field_name: selectedField,
          block_id: block.block_id,
          status: "verified",
          note: "Evidence audit workbench",
        }),
      });
      await refresh();
      if (comparison) await fetchComparison();
      else if (retrieval) await fetchRetrieval();
      setNotice("已加入 verified gold evidence。");
    });

  const removeGold = (blockId: string) =>
    runAction(`gold-${blockId}`, async () => {
      const record = state.gold.find(
        (gold) =>
          gold.block_id === blockId &&
          gold.field_name === selectedField &&
          gold.document_id === selectedDocumentId,
      );
      if (!record) return;
      await api(`/api/gold/${record.gold_id}`, { method: "DELETE" });
      await refresh();
      if (comparison) await fetchComparison();
      else if (retrieval) await fetchRetrieval();
      setNotice("已移除该 gold evidence。");
    });

  const searchBlocks = () =>
    runAction("block-search", async () => {
      if (!selectedDocumentId || !blockQuery.trim()) {
        throw new Error("请输入用于浏览全文证据的关键词。");
      }
      const result = await api<{ blocks: BlockRecord[] }>(
        `/api/documents/${selectedDocumentId}/blocks?query=${encodeURIComponent(
          blockQuery,
        )}&limit=80`,
      );
      setBlockSearch(result.blocks);
      setNotice(`全文浏览找到 ${result.blocks.length} 个证据块。`);
    });

  const browseAllBlocks = () =>
    runAction("block-browse-all", async () => {
      if (!selectedDocumentId) {
        throw new Error("请选择论文。");
      }
      const result = await api<{ blocks: BlockRecord[] }>(
        `/api/documents/${selectedDocumentId}/blocks?limit=300`,
      );
      setBlockQuery("");
      setBlockSearch(result.blocks);
      setNotice(
        `已载入 ${result.blocks.length} 个证据块，可逐条检查并补充 Gold。`,
      );
    });

  const runEvaluation = () =>
    runAction("evaluate", async () => {
      const result = await api<Evaluation>("/api/evaluate", {
        method: "POST",
        body: JSON.stringify({
          k_values: [3, 5, 10],
          gold_status: "verified",
        }),
      });
      setEvaluation(result);
      setState((current) => ({
        ...current,
        latest_evaluation: result,
      }));
      setNotice("已使用 verified gold evidence 完成检索评估。");
    });

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            E
          </span>
          <div>
            <strong>EcoEvidence</strong>
            <small>MVP 1.1 · 本地证据工作台</small>
          </div>
        </div>
        <div className="scope-note">
          <span className="live-dot" />
          当前范围止于证据召回评估
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-intro">
            <span className="eyebrow">WORKFLOW</span>
            <h1>从研究问题到可测量的证据召回</h1>
            <p>每一步都保留来源、规则和可替换边界。</p>
          </div>
          <nav aria-label="项目阶段">
            {STAGES.map((item) => {
              const active = stage === item.id;
              return (
                <button
                  className={`stage-link ${active ? "active" : ""}`}
                  data-testid={`stage-${item.id}`}
                  key={item.id}
                  onClick={() => setStage(item.id)}
                  type="button"
                >
                  <span>{item.step}</span>
                  {item.label}
                </button>
              );
            })}
          </nav>
          <div className="sidebar-foot">
            <span>语料目录</span>
            <code title={state.source_directory}>
              {state.source_directory
                ? state.source_directory.split("/").slice(-2).join("/")
                : "等待后端"}
            </code>
            <span>{state.documents.length} 篇已登记论文</span>
          </div>
        </aside>

        <section className="content">
          {(error || notice) && (
            <div
              className={`message ${error ? "error" : "success"}`}
              role="status"
            >
              <span>{error ? "!" : "✓"}</span>
              {error || notice}
              <button
                aria-label="关闭提示"
                onClick={() => {
                  setError("");
                  setNotice("");
                }}
                type="button"
              >
                ×
              </button>
            </div>
          )}

          {stage === "brief" && (
            <div className="stage-panel" data-testid="brief-panel">
              <div className="page-heading">
                <div>
                  <span className="eyebrow">01 · RESEARCH BRIEF</span>
                  <h2>先自由描述你真正需要的数据</h2>
                  <p>
                    系统负责拆解变量和筛选规则；你只需要核对它是否理解正确。
                  </p>
                </div>
                <span className="phase-badge">用户表达 → 机器拆解 → 用户确认</span>
              </div>

              <div className="brief-grid">
                <article className="card brief-card">
                  <label htmlFor="research-brief">研究需求</label>
                  <textarea
                    id="research-brief"
                    onChange={(event) => setBrief(event.target.value)}
                    placeholder="例如：我希望提取……必须包括……允许缺少……"
                    value={brief}
                  />
                  <div className="card-actions">
                    <span>{brief.length} 字</span>
                    <button
                      className="primary"
                      data-testid="interpret-brief"
                      disabled={busy === "interpret" || brief.length < 12}
                      onClick={interpretBrief}
                      type="button"
                    >
                      {busy === "interpret" ? "正在拆解…" : "解析这段需求"}
                    </button>
                  </div>
                </article>

                <article className="card interpretation-card">
                  <div className="card-title">
                    <div>
                      <span className="eyebrow">SYSTEM INTERPRETATION</span>
                      <h3>系统理解</h3>
                    </div>
                    <span className={state.spec ? "ready" : "pending"}>
                      {state.spec ? "待核对" : "未生成"}
                    </span>
                  </div>
                  {state.spec ? (
                    <div className="interpretation-body">
                      <FieldChips
                        fields={state.spec.target_variables}
                        title="目标变量"
                        tone="target"
                      />
                      <FieldChips
                        fields={state.spec.required_context}
                        title="必须上下文"
                        tone="required"
                      />
                      <FieldChips
                        fields={state.spec.optional_context}
                        title="关注字段"
                      />
                      <div className="field-group">
                        <span className="eyebrow">接受来源</span>
                        <div className="chip-row">
                          {state.spec.accepted_sources.map((source) => (
                            <span className="chip" key={source}>
                              {source}
                            </span>
                          ))}
                        </div>
                      </div>
                      {state.spec.exclusions.length ? (
                        <div className="policy-note">
                          排除：{state.spec.exclusions.join("、")}
                        </div>
                      ) : null}
                      {state.spec.interpretation_warnings.map((warning) => (
                        <p className="warning-line" key={warning}>
                          {warning}
                        </p>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state">
                      <span>01</span>
                      <p>解析需求后，这里会用少量标签展示系统理解。</p>
                    </div>
                  )}
                </article>
              </div>
              <div className="next-step">
                <div>
                  <strong>核对完成后</strong>
                  <span>进入全文解析，研究需求将自动参与四级文献筛选。</span>
                </div>
                <button
                  disabled={!state.spec}
                  onClick={() => setStage("documents")}
                  type="button"
                >
                  继续到全文解析 →
                </button>
              </div>
            </div>
          )}

          {stage === "documents" && (
            <div className="stage-panel" data-testid="documents-panel">
              <div className="page-heading">
                <div>
                  <span className="eyebrow">02 · FULL DOCUMENT PARSING</span>
                  <h2>全文只解析一次，筛选规则可以反复重建</h2>
                  <p>
                    SQLite 保存规范化证据块；相同 PDF
                    通过哈希复用，不生成重复全文文件。
                  </p>
                </div>
                <button
                  className="primary"
                  data-testid="sync-documents"
                  disabled={busy === "sync" || !state.spec}
                  onClick={syncDocuments}
                  type="button"
                >
                  {busy === "sync" ? "正在解析语料…" : "同步并解析语料"}
                </button>
              </div>

              <div className="metric-strip">
                <div>
                  <strong>{state.documents.length}</strong>
                  <span>论文</span>
                </div>
                <div>
                  <strong>{statusCounts.usable ?? 0}</strong>
                  <span>usable</span>
                </div>
                <div>
                  <strong>{statusCounts.relative ?? 0}</strong>
                  <span>relative</span>
                </div>
                <div>
                  <strong>{statusCounts.nodata ?? 0}</strong>
                  <span>nodata</span>
                </div>
                <div>
                  <strong>{statusCounts.failed ?? 0}</strong>
                  <span>failed</span>
                </div>
              </div>

              <div className="document-list">
                {state.documents.length ? (
                  state.documents.map((document) => (
                    <article className="document-row" key={document.document_id}>
                      <div className="document-index">
                        {String(document.page_count).padStart(2, "0")}
                        <small>页</small>
                      </div>
                      <div className="document-main">
                        <div className="document-title">
                          <h3>{document.title || document.filename}</h3>
                          <span className={`status ${document.screening_status}`}>
                            {statusLabel(document.screening_status)}
                          </span>
                        </div>
                        <p>{document.filename}</p>
                        <p className="document-summary">{document.summary}</p>
                        <div className="document-meta">
                          <span>{document.language.toUpperCase()}</span>
                          <span>
                            {document.text_char_count.toLocaleString()} 字符
                          </span>
                          <span>{document.block_count} 证据块</span>
                          <span>{document.figure_caption_count} 图题</span>
                          <span>{document.table_caption_count} 表题</span>
                          <span>parser: {document.parser_status}</span>
                          {document.missing_required_fields.length ? (
                            <span className="missing">
                              缺失 {document.missing_required_fields.join("、")}
                            </span>
                          ) : null}
                        </div>
                        {document.covered_fields.length ? (
                          <div className="coverage-row">
                            {document.covered_fields.map((field) => (
                              <span key={field}>{field}</span>
                            ))}
                          </div>
                        ) : null}
                        <details>
                          <summary>查看机器筛选依据</summary>
                          <ul>
                            {document.screening_reasons.map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                        </details>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="large-empty">
                    <span>PDF</span>
                    <h3>语料尚未解析</h3>
                    <p>确认研究需求后，点击“同步并解析语料”。</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {stage === "retrieval" && (
            <div className="stage-panel" data-testid="retrieval-panel">
              <div className="page-heading">
                <div>
                  <span className="eyebrow">03 · RETRIEVAL AUDIT</span>
                  <h2>看见模型召回了什么，也看见它漏掉什么</h2>
                  <p>
                    BM25、字符 n-gram 向量、术语覆盖和章节先验分别显示，便于定位错误。
                  </p>
                </div>
                <span className="phase-badge">当前基线：可离线复现</span>
              </div>

              <article className="card retrieval-controls">
                <label>
                  论文
                  <select
                    onChange={(event) => {
                      setSelectedDocumentId(event.target.value);
                      setRetrieval(null);
                      setComparison(null);
                      setBlockSearch([]);
                    }}
                    value={selectedDocumentId}
                  >
                    <option value="">请选择</option>
                    {state.documents.map((document) => (
                      <option
                        key={document.document_id}
                        value={document.document_id}
                      >
                        {document.filename}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  证据字段
                  <select
                    onChange={(event) => {
                      setSelectedField(event.target.value);
                      setRetrieval(null);
                      setComparison(null);
                    }}
                    value={selectedField}
                  >
                    <option value="">请选择</option>
                    {availableFields.map((field) => (
                      <option key={field.name} value={field.name}>
                        {field.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Top K
                  <select
                    onChange={(event) => setTopK(Number(event.target.value))}
                    value={topK}
                  >
                    {[3, 5, 8, 10, 15].map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <button
                  className="primary"
                  data-testid="run-retrieval"
                  disabled={
                    busy === "retrieve" ||
                    !selectedDocumentId ||
                    !selectedField
                  }
                  onClick={runRetrieval}
                  type="button"
                >
                  {busy === "retrieve" ? "正在召回…" : "运行证据召回"}
                </button>
                <button
                  className="comparison-button"
                  data-testid="run-retrieval-comparison"
                  disabled={
                    busy === "compare" ||
                    !selectedDocumentId ||
                    !selectedField
                  }
                  onClick={runComparison}
                  type="button"
                >
                  {busy === "compare" ? "正在比较…" : "比较三种方法"}
                </button>
              </article>

              {comparison ? (
                <section
                  className="comparison-section"
                  data-testid="retrieval-comparison"
                >
                  <div className="section-heading comparison-heading">
                    <div>
                      <span className="eyebrow">SIDE-BY-SIDE AUDIT</span>
                      <h3>同一查询的检索方法对照</h3>
                    </div>
                    <code>{comparison.comparison_id}</code>
                  </div>
                  <div className="query-box">
                    <span>冻结查询 · verified Gold</span>
                    <p>{comparison.query}</p>
                  </div>
                  <div className="comparison-grid">
                    {comparison.items.map((item) => {
                      const response = item.retrieval;
                      return (
                        <article
                          className={`comparison-column strategy-${item.strategy}`}
                          key={item.strategy}
                        >
                          <header>
                            <div>
                              <span>{item.strategy}</span>
                              <h4>{item.label}</h4>
                            </div>
                            <strong
                              className={
                                item.status === "available"
                                  ? "available"
                                  : "unavailable"
                              }
                            >
                              {item.status === "available" ? "可运行" : "不可用"}
                            </strong>
                          </header>
                          {response && item.metrics ? (
                            <>
                              <dl className="comparison-metrics">
                                <div>
                                  <dt>Gold 首位</dt>
                                  <dd>
                                    {item.metrics.gold_count
                                      ? item.metrics.first_gold_rank
                                        ? `#${item.metrics.first_gold_rank}`
                                        : "未命中"
                                      : "未标注"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Hit@{comparison.k}</dt>
                                  <dd>
                                    {item.metrics.hit_at_k === null
                                      ? "—"
                                      : percent(item.metrics.hit_at_k)}
                                  </dd>
                                </div>
                                <div>
                                  <dt>Recall@{comparison.k}</dt>
                                  <dd>
                                    {item.metrics.recall_at_k === null
                                      ? "—"
                                      : percent(item.metrics.recall_at_k)}
                                  </dd>
                                </div>
                                <div>
                                  <dt>耗时</dt>
                                  <dd>{response.elapsed_ms.toFixed(1)} ms</dd>
                                </div>
                              </dl>
                              <code className="comparison-identity">
                                {response.backend.backend}/{response.backend.model}@
                                {response.backend.model_version}
                              </code>
                              <div className="comparison-hits">
                                {response.hits.map((hit) => {
                                  const gold = state.gold.some(
                                    (record) =>
                                      record.block_id === hit.block.block_id &&
                                      record.field_name === selectedField &&
                                      record.document_id === selectedDocumentId,
                                  );
                                  const baseline = comparison.items
                                    .find(
                                      (candidate) =>
                                        candidate.strategy === "bm25-only",
                                    )
                                    ?.retrieval?.hits.find(
                                      (candidate) =>
                                        candidate.block.block_id ===
                                        hit.block.block_id,
                                    );
                                  const rankDelta = baseline
                                    ? baseline.rank - hit.rank
                                    : null;
                                  return (
                                    <article
                                      className={gold ? "gold" : ""}
                                      key={hit.block.block_id}
                                    >
                                      <div className="comparison-hit-meta">
                                        <strong>#{hit.rank}</strong>
                                        <span>p.{hit.block.page}</span>
                                        <span>{hit.block.section}</span>
                                        {item.strategy !== "bm25-only" ? (
                                          <em>
                                            {rankDelta === null
                                              ? "BM25 Top K 外"
                                              : rankDelta > 0
                                                ? `较 BM25 ↑${rankDelta}`
                                                : rankDelta < 0
                                                  ? `较 BM25 ↓${Math.abs(rankDelta)}`
                                                  : "与 BM25 同位"}
                                          </em>
                                        ) : null}
                                      </div>
                                      <p>{hit.block.text}</p>
                                      <div className="comparison-hit-score">
                                        <span>总分 {hit.score.toFixed(3)}</span>
                                        <span>
                                          BM25 {hit.score_components.bm25.toFixed(2)}
                                        </span>
                                        <span>
                                          Semantic{" "}
                                          {hit.score_components.semantic.toFixed(2)}
                                        </span>
                                      </div>
                                      <button
                                        className={
                                          gold
                                            ? "gold-button active"
                                            : "gold-button"
                                        }
                                        disabled={
                                          busy === `gold-${hit.block.block_id}`
                                        }
                                        onClick={() =>
                                          gold
                                            ? removeGold(hit.block.block_id)
                                            : addGold(hit.block)
                                        }
                                        type="button"
                                      >
                                        {gold ? "✓ Gold" : "+ Gold"}
                                      </button>
                                    </article>
                                  );
                                })}
                              </div>
                            </>
                          ) : (
                            <div className="comparison-unavailable">
                              <strong>E5 可选运行时尚未就绪</strong>
                              <p>{item.error}</p>
                            </div>
                          )}
                        </article>
                      );
                    })}
                  </div>
                  <p className="comparison-note">
                    排名变化以 BM25-only 为基准；三列使用同一字段查询、同一论文和同一组
                    verified Gold。冷启动耗时可能包含 E5 模型加载，重复运行可观察热缓存。
                  </p>
                </section>
              ) : null}

              {retrieval ? (
                <div className="retrieval-layout">
                  <section className="results-column">
                    <div className="section-heading">
                      <div>
                        <span className="eyebrow">TOP {topK}</span>
                        <h3>机器召回结果</h3>
                      </div>
                      <code>
                        {retrieval.retrieval_version} · {retrieval.backend.backend}/
                        {retrieval.backend.model}@{retrieval.backend.model_version} ·{" "}
                        {retrieval.elapsed_ms.toFixed(2)} ms · cache H
                        {retrieval.cache.hits}/M{retrieval.cache.misses}/W
                        {retrieval.cache.writes}
                      </code>
                    </div>
                    <div className="query-box">
                      <span>查询扩展</span>
                      <p>{retrieval.query}</p>
                    </div>
                    {retrieval.hits.map((hit) => {
                      const gold = state.gold.some(
                        (record) =>
                          record.block_id === hit.block.block_id &&
                          record.field_name === selectedField,
                      );
                      return (
                        <article
                          className={`evidence-card ${gold ? "gold" : ""}`}
                          key={hit.block.block_id}
                        >
                          <div className="rank">{hit.rank}</div>
                          <div className="evidence-content">
                            <div className="evidence-meta">
                              <span>p.{hit.block.page}</span>
                              <span>{hit.block.section}</span>
                              <span>{hit.block.kind}</span>
                              <strong>{hit.score.toFixed(3)}</strong>
                            </div>
                            <p>{hit.block.text}</p>
                            <div className="score-bars">
                              {Object.entries(hit.score_components).map(
                                ([name, value]) => (
                                  <div key={name}>
                                    <span>
                                      {name.replace("term_coverage", "terms")}
                                    </span>
                                    <i>
                                      <b style={{ width: `${value * 100}%` }} />
                                    </i>
                                    <small>{value.toFixed(2)}</small>
                                  </div>
                                ),
                              )}
                            </div>
                            <div className="evidence-actions">
                              <span>
                                命中：
                                {hit.matched_terms.length
                                  ? hit.matched_terms.join("、")
                                  : "仅语义/结构"}
                              </span>
                              <button
                                className={gold ? "gold-button active" : "gold-button"}
                                disabled={busy === `gold-${hit.block.block_id}`}
                                onClick={() =>
                                  gold
                                    ? removeGold(hit.block.block_id)
                                    : addGold(hit.block)
                                }
                                type="button"
                              >
                                {gold ? "✓ Gold evidence" : "+ 标记为 Gold"}
                              </button>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </section>

                  <aside className="audit-column">
                    <div className="section-heading">
                      <div>
                        <span className="eyebrow">MISS AUDIT</span>
                        <h3>全文补漏</h3>
                      </div>
                    </div>
                    <p className="aside-copy">
                      如果 Top K 没有正确证据，用精确词浏览全部证据块，并把遗漏项加入
                      Gold。
                    </p>
                    <div className="block-search">
                      <input
                        onChange={(event) => setBlockQuery(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") searchBlocks();
                        }}
                        placeholder="例如：n =、sample、样本"
                        value={blockQuery}
                      />
                      <button
                        disabled={busy === "block-search"}
                        onClick={searchBlocks}
                        type="button"
                      >
                        搜索全文
                      </button>
                      <button
                        disabled={busy === "block-browse-all"}
                        onClick={browseAllBlocks}
                        type="button"
                      >
                        浏览全部
                      </button>
                    </div>
                    <div className="gold-summary">
                      <strong>
                        {
                          state.gold.filter(
                            (gold) =>
                              gold.document_id === selectedDocumentId &&
                              gold.field_name === selectedField,
                          ).length
                        }
                      </strong>
                      <span>条 verified gold</span>
                    </div>
                    <div className="block-results">
                      {blockSearch.map((block) => {
                        const gold = state.gold.some(
                          (record) =>
                            record.block_id === block.block_id &&
                            record.field_name === selectedField,
                        );
                        return (
                          <article key={block.block_id}>
                            <span>
                              p.{block.page} · {block.section}
                            </span>
                            <p>{block.text}</p>
                            <button
                              onClick={() =>
                                gold
                                  ? removeGold(block.block_id)
                                  : addGold(block)
                              }
                              type="button"
                            >
                              {gold ? "移除 Gold" : "这是正确证据"}
                            </button>
                          </article>
                        );
                      })}
                      {!blockSearch.length ? (
                        <div className="mini-empty">
                          <span>⌕</span>
                          <p>这里用于发现 Top K 之外的漏召回证据。</p>
                        </div>
                      ) : null}
                    </div>
                  </aside>
                </div>
              ) : (
                <div className="large-empty retrieval-empty">
                  <span>R@K</span>
                  <h3>选择一篇论文和一个字段</h3>
                  <p>
                    运行后将展示每个结果的来源、排名和四个分数组件。
                  </p>
                </div>
              )}
            </div>
          )}

          {stage === "evaluation" && (
            <div className="stage-panel" data-testid="evaluation-panel">
              <div className="page-heading">
                <div>
                  <span className="eyebrow">04 · QUANTITATIVE EVALUATION</span>
                  <h2>用 verified gold 计算真实的召回表现</h2>
                  <p>
                    将“解析遗漏、检索遗漏、后续抽取错误”分开，避免一个准确率掩盖问题。
                  </p>
                </div>
                <button
                  className="primary"
                  data-testid="run-evaluation"
                  disabled={busy === "evaluate" || !state.gold.length}
                  onClick={runEvaluation}
                  type="button"
                >
                  {busy === "evaluate" ? "正在计算…" : "运行 Recall@K 评估"}
                </button>
              </div>

              <div className="evaluation-callout">
                <div>
                  <span className="eyebrow">GOLD COVERAGE</span>
                  <strong>{state.gold.length}</strong>
                  <p>条人工证据标注</p>
                </div>
                <p>
                  没有人工 gold 就没有真实的 Recall。请先在“证据召回审计”中标记正确证据，
                  尤其要用“全文补漏”加入 Top K 之外的证据。
                </p>
              </div>

              {evaluation ? (
                <>
                  <div className="evaluation-hero">
                    <article>
                      <span>Recall@5</span>
                      <strong>
                        {percent(evaluation.metrics_at_k["5"]?.recall)}
                      </strong>
                      <small>正确证据被召回的比例</small>
                    </article>
                    <article>
                      <span>Precision@5</span>
                      <strong>
                        {percent(evaluation.metrics_at_k["5"]?.precision)}
                      </strong>
                      <small>Top 5 中真正相关的比例</small>
                    </article>
                    <article>
                      <span>Hit@5</span>
                      <strong>
                        {percent(evaluation.metrics_at_k["5"]?.hit_rate)}
                      </strong>
                      <small>至少命中一条的查询比例</small>
                    </article>
                    <article>
                      <span>MRR</span>
                      <strong>{evaluation.mean_reciprocal_rank.toFixed(2)}</strong>
                      <small>第一条正确证据的平均排名</small>
                    </article>
                  </div>

                  <div className="evaluation-grid">
                    <article className="card">
                      <div className="section-heading">
                        <div>
                          <span className="eyebrow">K SENSITIVITY</span>
                          <h3>不同 Top K 的表现</h3>
                        </div>
                      </div>
                      <table>
                        <thead>
                          <tr>
                            <th>K</th>
                            <th>Hit</th>
                            <th>Recall</th>
                            <th>Precision</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(evaluation.metrics_at_k).map(
                            ([k, metrics]) => (
                              <tr key={k}>
                                <td>Top {k}</td>
                                <td>{percent(metrics.hit_rate)}</td>
                                <td>{percent(metrics.recall)}</td>
                                <td>{percent(metrics.precision)}</td>
                              </tr>
                            ),
                          )}
                        </tbody>
                      </table>
                    </article>

                    <article className="card">
                      <div className="section-heading">
                        <div>
                          <span className="eyebrow">EVALUATION COVERAGE</span>
                          <h3>评估覆盖</h3>
                        </div>
                      </div>
                      <dl className="coverage-list">
                        <div>
                          <dt>已评估查询</dt>
                          <dd>{evaluation.coverage.evaluated_queries}</dd>
                        </div>
                        <div>
                          <dt>Gold 证据块</dt>
                          <dd>{evaluation.coverage.gold_blocks}</dd>
                        </div>
                        <div>
                          <dt>覆盖论文</dt>
                          <dd>{evaluation.coverage.documents}</dd>
                        </div>
                        <div>
                          <dt>覆盖字段</dt>
                          <dd>{evaluation.coverage.fields}</dd>
                        </div>
                        {typeof evaluation.coverage.vector_cache_hits ===
                        "number" ? (
                          <div>
                            <dt>向量缓存命中</dt>
                            <dd>{evaluation.coverage.vector_cache_hits}</dd>
                          </div>
                        ) : null}
                        {typeof evaluation.coverage.vector_cache_misses ===
                        "number" ? (
                          <div>
                            <dt>向量缓存未命中</dt>
                            <dd>{evaluation.coverage.vector_cache_misses}</dd>
                          </div>
                        ) : null}
                      </dl>
                    </article>
                  </div>

                  <article className="card per-field-card">
                    <div className="section-heading">
                      <div>
                        <span className="eyebrow">FIELD BREAKDOWN</span>
                        <h3>按字段诊断</h3>
                      </div>
                      <code>
                        {evaluation.retrieval_version}
                        {evaluation.backend
                          ? ` · ${evaluation.backend.backend}/${evaluation.backend.model}@${evaluation.backend.model_version}`
                          : ""}
                        {evaluation.timing
                          ? ` · ${evaluation.timing.retrieval_elapsed_ms.toFixed(2)} ms`
                          : ""}
                      </code>
                    </div>
                    <table>
                      <thead>
                        <tr>
                          <th>字段</th>
                          <th>查询数</th>
                          <th>Gold</th>
                          <th>Recall@5</th>
                          <th>Precision@5</th>
                          <th>MRR</th>
                        </tr>
                      </thead>
                      <tbody>
                        {evaluation.per_field.map((field) => (
                          <tr key={field.field_name}>
                            <td>{field.field_name}</td>
                            <td>{field.query_count}</td>
                            <td>{field.gold_count}</td>
                            <td>{percent(field.metrics["5"]?.recall)}</td>
                            <td>{percent(field.metrics["5"]?.precision)}</td>
                            <td>{field.mrr.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </article>
                </>
              ) : (
                <div className="large-empty">
                  <span>0.00</span>
                  <h3>尚无评估结果</h3>
                  <p>完成至少一条 verified gold 标注后运行评估。</p>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
