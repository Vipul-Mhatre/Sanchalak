import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://localhost:8000' : '')

// ---------------------------------------------------------------------------
// Icons (inline SVG — no emoji)
// ---------------------------------------------------------------------------

const ic = (path, size = 16) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {path}
  </svg>
)

const IconLogo = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M12 2l8.5 5v10L12 22l-8.5-5V7L12 2zm0 2.3L5.5 8.4v7.2L12 19.7l6.5-4.1V8.4L12 4.3z" />
    <circle cx="12" cy="12" r="2.6" />
  </svg>
)

const IconSend = () => ic(<path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />)
const IconRefresh = () => ic(<path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />)
const IconChart = () => ic(<><path d="M3 3v18h18" /><path d="M7 15v-3M12 15V8M17 15v-6" /></>)
const IconCopy = () => ic(<><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>)
const IconCheck = () => ic(<path d="M20 6L9 17l-5-5" />)
const IconClose = () => ic(<path d="M18 6L6 18M6 6l12 12" />)
const IconBook = () => ic(<><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></>)
const IconDb = () => ic(<><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" /></>)
const IconLink = () => ic(<><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></>)
const IconAlert = () => ic(<><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><path d="M12 9v4M12 17h.01" /></>)
const IconSparkle = () => ic(<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />)

// ---------------------------------------------------------------------------
// Markdown (line-based block parser + inline tokens, citation-aware)
// ---------------------------------------------------------------------------

const esc = (s) => String(s)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')

const INLINE_RE = /(`[^`]+`)|\[([^\]]+)\]|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)/g

function renderInline(raw, citMap, onCite) {
  const out = []
  let last = 0
  let m
  const re = new RegExp(INLINE_RE.source, 'g')
  while ((m = re.exec(raw)) !== null) {
    if (m.index > last) out.push(esc(raw.slice(last, m.index)))
    if (m[1]) {
      out.push(<code key={m.index} className="md-code">{m[1].slice(1, -1)}</code>)
    } else if (m[2]) {
      const key = m[2].trim().replace(/^docs:\s*/i, '')
      const cit = citMap.get(key)
      if (cit) {
        out.push(<CitationChip key={m.index} cit={cit} inline onClick={onCite} />)
      } else {
        out.push(<span key={m.index} className="md-bracket">[{m[2].trim()}]</span>)
      }
    } else if (m[3]) {
      out.push(<strong key={m.index}>{m[4]}</strong>)
    } else if (m[5]) {
      out.push(<em key={m.index}>{m[6]}</em>)
    }
    last = re.lastIndex
  }
  if (last < raw.length) out.push(esc(raw.slice(last)))
  return out
}

function renderMarkdown(text, citMap, onCite) {
  if (!text) return null
  const lines = text.split('\n')
  const out = []
  let list = null
  let para = []
  let fence = null
  let key = 0

  const flushPara = () => {
    if (para.length) {
      out.push(<p key={key++} className="md-p">{renderInline(para.join(' '), citMap, onCite)}</p>)
      para = []
    }
  }
  const flushList = () => {
    if (list) {
      out.push(list.ordered
        ? <ol key={key++} className="md-ol">{list.items.map((it, i) => <li key={i}>{it}</li>)}</ol>
        : <ul key={key++} className="md-ul">{list.items.map((it, i) => <li key={i}>{it}</li>)}</ul>)
      list = null
    }
  }

  for (const raw of lines) {
    if (fence !== null) {
      if (raw.trim().startsWith('```')) { out.push(<pre key={key++} className="md-pre"><code>{fence}</code></pre>); fence = null }
      else fence += raw + '\n'
      continue
    }
    const t = raw.trim()
    if (t.startsWith('```')) { flushList(); flushPara(); fence = ''; continue }
    if (!t) { flushList(); flushPara(); continue }
    const h = t.match(/^(#{1,3})\s+(.*)$/)
    if (h) {
      flushList(); flushPara()
      const level = h[1].length
      out.push(<div key={key++} className={`md-h md-h${level}`}>{renderInline(h[2], citMap, onCite)}</div>)
      continue
    }
    if (/^[-•]\s+/.test(t)) {
      flushPara()
      if (!list) list = { ordered: false, items: [] }
      list.items.push(<span key={list.items.length}>{renderInline(t.replace(/^[-•]\s+/, ''), citMap, onCite)}</span>)
      continue
    }
    if (/^\d+\.\s+/.test(t)) {
      flushPara()
      if (!list) list = { ordered: true, items: [] }
      list.items.push(<span key={list.items.length}>{renderInline(t.replace(/^\d+\.\s+/, ''), citMap, onCite)}</span>)
      continue
    }
    if (/^>\s?/.test(t)) {
      flushList(); flushPara()
      out.push(<blockquote key={key++} className="md-quote">{renderInline(t.replace(/^>\s?/, ''), citMap, onCite)}</blockquote>)
      continue
    }
    if (/^---+$/.test(t)) { flushList(); flushPara(); out.push(<hr key={key++} className="md-hr" />); continue }
    flushList()
    para.push(t)
  }
  flushList(); flushPara()
  return out
}

// ---------------------------------------------------------------------------
// Citation chip
// ---------------------------------------------------------------------------

function CitationChip({ cit, inline, onClick }) {
  const kind = cit.type === 'docs' ? 'docs' : cit.type === 'both' ? 'both' : 'customer'
  const label = cit.type === 'docs'
    ? (cit.title || (cit.url || cit.id).split('/').filter(Boolean).pop() || cit.id)
    : cit.id
  const Icon = cit.type === 'docs' ? IconBook : IconDb
  return (
    <button
      type="button"
      className={`citation-chip ${kind} ${inline ? 'inline' : ''}`}
      onClick={(e) => { e.stopPropagation(); onClick?.(cit) }}
      title={cit.type === 'docs' ? (cit.url || cit.id) : `${cit.record_type || 'record'} ${cit.id}`}
    >
      <Icon size={12} />
      <span className="chip-label">{label}</span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Agent turn
// ---------------------------------------------------------------------------

function AgentTurn({ msg }) {
  const [expanded, setExpanded] = useState(null)
  const [copied, setCopied] = useState(false)
  const [detail, setDetail] = useState(null)

  const citMap = useMemo(() => {
    const m = new Map()
    for (const c of msg.citations || []) if (!m.has(c.id)) m.set(c.id, c)
    return m
  }, [msg.citations])

  const kinds = useMemo(() => {
    const s = new Set()
    for (const c of msg.citations || []) s.add(c.type === 'docs' ? 'docs' : 'customer')
    return s
  }, [msg.citations])

  const sourcesLabel = useMemo(() => {
    if (kinds.has('docs') && kinds.has('customer')) return 'Customer data + Live docs'
    if (kinds.has('docs')) return 'Live docs'
    if (kinds.has('customer')) return 'Customer data'
    return null
  }, [kinds])

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(msg.content || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard unavailable */ }
  }

  const openDetail = (cit) => {
    setExpanded(expanded === cit.id ? null : cit.id)
    setDetail(cit)
  }

  return (
    <div className="agent-turn">
      <div className="turn-head">
        <div className="turn-avatar"><IconSparkle size={14} /></div>
        {sourcesLabel && <span className={`source-pill ${sourcesLabel.includes('+') ? 'both' : kinds.has('docs') ? 'docs' : 'customer'}`}>{sourcesLabel}</span>}
        <button type="button" className="copy-btn" onClick={copyAnswer} title="Copy answer">
          {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
        </button>
      </div>

      {msg.contradictions?.length > 0 && (
        <div className="contradiction-banner">
          <span className="contradiction-icon"><IconAlert size={15} /></span>
          <div className="contradiction-body">
            <div className="contradiction-title">Requested — but already in docs</div>
            {msg.contradictions.map((c, i) => (
              <div key={i} className="contradiction-item">
                <div className="contradiction-fr">
                  {c.feature_request_id && <span className="contradiction-id">{c.feature_request_id}</span>}
                  {c.title || 'Feature request'}
                </div>
                {c.requesting_accounts?.length > 0 && (
                  <div className="contradiction-accounts">
                    Requested by: {c.requesting_accounts.join(', ')}
                  </div>
                )}
                {c.doc_url && (
                  <a className="contradiction-doc" href={c.doc_url} target="_blank" rel="noopener noreferrer">
                    <IconLink size={11} /> {c.doc_url}
                  </a>
                )}
                {c.explanation && <div className="contradiction-text">{c.explanation}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={`turn-content ${msg.error ? 'is-error' : ''}`}>
        {msg.error ? (
          <div className="error-box">
            <IconAlert size={16} />
            <span>{msg.content}</span>
          </div>
        ) : (
          renderMarkdown(msg.content, citMap, openDetail)
        )}
      </div>

      {detail && expanded && (
        <div className="citation-detail">
          <div className="detail-kind">
            {detail.type === 'docs' ? <IconBook size={12} /> : <IconDb size={12} />}
            {detail.type === 'docs' ? 'Docs page' : detail.record_type || 'Record'}
            {detail.type !== 'docs' && detail.id && <span className="detail-id">{detail.id}</span>}
          </div>
          {detail.type === 'docs' && detail.url && (
            <a className="detail-link" href={detail.url} target="_blank" rel="noopener noreferrer">
              <IconLink size={12} /> {detail.url}
            </a>
          )}
          {detail.content_preview && <p className="detail-preview">{detail.content_preview}</p>}
        </div>
      )}

      {msg.citations?.length > 0 && (
        <div className="citations-row">
          {Array.from(citMap.values()).map((c, i) => (
            <CitationChip key={i} cit={c} onClick={openDetail} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------

function ReindexPanel({ reindexLog, reindexBusy, onRun }) {
  return (
    <div className="panel-content">
      <p className="panel-hint">
        Edit a record in <code>dataset/</code>, then run delta reindex. Only changed records are
        re-embedded — no full rebuild.
      </p>
      <button type="button" className="reindex-run" onClick={onRun} disabled={reindexBusy}>
        <IconRefresh size={14} />
        {reindexBusy ? 'Running…' : 'Run Delta Reindex'}
      </button>
      <div className="reindex-log">
        {reindexLog.length === 0 && <div className="log-empty">No reindex operations yet.</div>}
        {reindexLog.map((e, i) => (
          <div key={i} className="log-entry">
            <span className="log-time">{e.time}</span>
            <span className="log-msg">{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function UsagePanel({ usageData }) {
  if (!usageData) {
    return <div className="panel-content"><div className="log-empty">Loading usage…</div></div>
  }
  const breakdown = Object.entries(usageData.source_breakdown || {})
  const total = usageData.total_queries || 0
  return (
    <div className="panel-content">
      <div className="stat-card">
        <div className="stat-label">Total queries</div>
        <div className="stat-value">{total}</div>
      </div>
      {breakdown.length > 0 && (
        <div className="stat-card">
          <div className="stat-label">Source breakdown</div>
          <div className="breakdown">
            {breakdown.map(([k, v]) => (
              <div key={k} className="breakdown-row">
                <span className={`breakdown-dot ${k === 'docs' ? 'docs' : 'customer'}`} />
                <span className="breakdown-name">{k === 'customer_data' ? 'Customer data' : 'Live docs'}</span>
                <span className="breakdown-value">{v}</span>
                {total > 0 && <span className="breakdown-bar"><span style={{ width: `${(v / total) * 100}%` }} /></span>}
              </div>
            ))}
          </div>
        </div>
      )}
      {usageData.most_asked?.length > 0 && (
        <div className="stat-card">
          <div className="stat-label">Most asked</div>
          <div className="most-asked">
            {usageData.most_asked.slice(0, 5).map((q, i) => (
              <div key={i} className="asked-row">
                <span className="asked-count">{q.count}×</span>
                <span className="asked-q">{q.question}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

const SUGGESTIONS = [
  { label: 'Open issues for Meridian AgriTech', q: 'What are the open issues for Meridian AgriTech?' },
  { label: 'How mission scheduling works', q: 'How does mission scheduling work in FlytBase?' },
  { label: 'Features already supported', q: 'Which accounts requested a feature that the platform already supports according to the docs?' },
  { label: 'Unanswerable test', q: 'What is the weather on Mars?' },
]

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [panel, setPanel] = useState(null) // 'reindex' | 'usage' | null
  const [reindexLog, setReindexLog] = useState([])
  const [reindexBusy, setReindexBusy] = useState(false)
  const [usageData, setUsageData] = useState(null)
  const [health, setHealth] = useState('checking') // checking | ok | error
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, loading])

  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`)
        const data = await res.json()
        if (alive) setHealth(data.status === 'ok' ? 'ok' : 'error')
      } catch {
        if (alive) setHealth('error')
      }
    }
    check()
    const id = setInterval(check, 15000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const sendMessage = async (question) => {
    const q = (question ?? input).trim()
    if (!q || loading) return
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setMessages(prev => [...prev, { role: 'user', content: q }])
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Request failed')
      }
      const data = await res.json()
      setMessages(prev => [...prev, { role: 'agent', content: data.answer, citations: data.citations || [], contradictions: data.contradictions || [] }])
    } catch (err) {
      setMessages(prev => [...prev, { role: 'agent', content: err.message, error: true }])
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    sendMessage()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const autoGrow = (e) => {
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }

  const handleReindex = async () => {
    if (reindexBusy) return
    setReindexBusy(true)
    setReindexLog(prev => [...prev, { time: new Date().toLocaleTimeString(), message: 'Running delta reindex…' }])
    try {
      const res = await fetch(`${API_BASE}/api/reindex`, { method: 'POST' })
      const data = await res.json()
      const msg = data.status === 'no_changes'
        ? 'No changes detected — index is up to date.'
        : `Updated: ${data.records_updated} re-embedded, ${data.records_deleted} removed. ${(data.changed_files || []).join(', ')}`
      setReindexLog(prev => [...prev, { time: new Date().toLocaleTimeString(), message: msg }])
    } catch (err) {
      setReindexLog(prev => [...prev, { time: new Date().toLocaleTimeString(), message: `Error: ${err.message}` }])
    } finally {
      setReindexBusy(false)
    }
  }

  const openUsage = async () => {
    setPanel(panel === 'usage' ? null : 'usage')
    if (panel !== 'usage') {
      try {
        const res = await fetch(`${API_BASE}/api/usage`)
        setUsageData(await res.json())
      } catch {
        setUsageData(null)
      }
    }
  }

  const togglePanel = (name) => setPanel(panel === name ? null : name)

  return (
    <div className="app">
      <div className="bg-glow" aria-hidden="true" />

      <header className="header">
        <div className="brand">
          <span className="brand-mark"><IconLogo /></span>
          <div className="brand-text">
            <span className="brand-name">Sanchalak</span>
            <span className="brand-sub">A Cross-Source Knowledge Agent for Solutions Engineering</span>
          </div>
        </div>
        <div className="header-right">
          <span className={`health-pill ${health}`} title={health === 'ok' ? 'Backend online' : health === 'error' ? 'Backend offline' : 'Checking backend…'}>
            <span className="health-dot" />
            {health === 'ok' ? 'Online' : health === 'error' ? 'Offline' : '…'}
          </span>
          <button type="button" className={`header-btn ${panel === 'reindex' ? 'active' : ''}`} onClick={() => togglePanel('reindex')}>
            <IconRefresh size={14} /> Reindex
          </button>
          <button type="button" className={`header-btn ${panel === 'usage' ? 'active' : ''}`} onClick={openUsage}>
            <IconChart size={14} /> Usage
          </button>
        </div>
      </header>

      <div className="layout">
        <main className="chat">
          <div className="messages">
            {messages.length === 0 && (
              <div className="welcome">
                <span className="welcome-mark"><IconLogo /></span>
                <h1>Ask about customers, docs, or both</h1>
                <p>
                  Grounded answers with inline citations — every claim traces to a record ID
                  or a live docs page.
                </p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s, i) => (
                    <button key={i} type="button" className="suggestion" onClick={() => sendMessage(s.q)}>
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => msg.role === 'user' ? (
              <div key={i} className="user-turn">
                <div className="user-bubble">{msg.content}</div>
              </div>
            ) : (
              <AgentTurn key={i} msg={msg} />
            ))}

            {loading && (
              <div className="agent-turn is-typing">
                <div className="typing-dots"><span /><span /><span /></div>
                <span className="typing-label">Searching corpus & live docs…</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <form className="composer" onSubmit={handleSubmit}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onInput={autoGrow}
              rows={1}
              placeholder="Ask about customers, docs, or both…"
              disabled={loading}
            />
            <button type="submit" className="send-btn" disabled={loading || !input.trim()} title="Send">
              {loading ? <span className="send-spinner" /> : <IconSend size={17} />}
            </button>
          </form>
          <div className="composer-note">Enter to send · answers cite record IDs and doc URLs</div>
        </main>

        {panel && (
          <>
            <div className="panel-backdrop" onClick={() => setPanel(null)} />
            <aside className="side-panel">
              <div className="panel-header">
                <h3>{panel === 'reindex' ? 'Delta Reindex' : 'Usage Stats'}</h3>
                <button type="button" className="panel-close" onClick={() => setPanel(null)} aria-label="Close panel">
                  <IconClose size={15} />
                </button>
              </div>
              {panel === 'reindex'
                ? <ReindexPanel reindexLog={reindexLog} reindexBusy={reindexBusy} onRun={handleReindex} />
                : <UsagePanel usageData={usageData} />}
            </aside>
          </>
        )}
      </div>
    </div>
  )
}

export default App
