import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import './App.css'
import { USE_MOCK, MOCK_STATES, MOCK_REINDEX_SEED, mockReindexEvent } from './mockData'

const API_BASE = 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function typeOf(cit) {
  if (cit.type === 'docs') return 'docs'
  if (cit.type === 'both') return 'both'
  return 'customer'
}

function chipLabel(cit) {
  if (cit.type === 'docs') return cit.title || (cit.url || cit.id).split('/').pop() || cit.id
  return cit.id
}

function railLabel(cit) {
  const label = chipLabel(cit)
  return label.length > 48 ? label.slice(0, 46) + '…' : label
}

function detailMarkup(cit) {
  const parts = []
  if (cit.type === 'docs') {
    parts.push(`<div class="detail-title">${esc(cit.title || 'Documentation page')}</div>`)
    if (cit.url) {
      parts.push(`<a class="detail-link" href="${esc(cit.url)}" target="_blank" rel="noopener noreferrer">${esc(cit.url)}</a>`)
    }
  } else {
    parts.push(`<div class="detail-title">${esc(cit.record_type || 'record')} · ${esc(cit.id)}</div>`)
  }
  if (cit.content_preview) {
    parts.push(`<div class="detail-preview">${esc(cit.content_preview)}</div>`)
  }
  return parts.join('')
}

// Citation token [id] or [url] inside answer text becomes a chip.
function renderInline(raw, citMap, expandedKey) {
  let s = esc(raw)
  s = s.replace(/\[([^\]]+)\]/g, (m, inner) => {
    const key = inner.trim().replace(/^docs:\s*/i, '')
    const cit = citMap.get(key)
    if (!cit) return m
    const cls = typeOf(cit)
    const stale = cit.stale ? '<span class="stale-indicator" title="Live fetch failed — showing cached copy"><span class="stale-dot"></span>cached</span>' : ''
    const detail = expandedKey === cit.id ? `<span class="chip-detail">${detailMarkup(cit)}</span>` : ''
    return `<span class="chip-wrap"><button type="button" class="citation-chip ${cls}" data-src="${esc(cit.id)}" aria-label="Source: ${esc(chipLabel(cit))}">${esc(chipLabel(cit))}</button>${stale}${detail}</span>`
  })
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>')
  return s
}

function renderAnswer(text, citMap, expandedKey) {
  if (!text) return ''
  const out = []
  let list = []
  const flush = () => {
    if (list.length) {
      out.push(`<ul class="answer-list">${list.join('')}</ul>`)
      list = []
    }
  }
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (!line) {
      flush()
      continue
    }
    const inline = (t) => renderInline(t, citMap, expandedKey)
    const h = line.match(/^(#{1,3})\s+(.*)$/)
    if (h) {
      flush()
      const level = h[1].length
      out.push(`<h${level}>${inline(h[2])}</h${level}>`)
    } else if (/^[-•]\s+/.test(line)) {
      list.push(`<li>${inline(line.replace(/^[-•]\s+/, ''))}</li>`)
    } else if (/^\d+\.\s+/.test(line)) {
      flush()
      const m = line.match(/^(\d+\.)\s*(.*)$/)
      out.push(`<p class="answer-num"><span class="answer-num-label">${m[1]}</span> ${inline(m[2])}</p>`)
    } else {
      flush()
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  flush()
  return out.join('')
}

// ---------------------------------------------------------------------------
// Streaming — token-by-token reveal, disabled under prefers-reduced-motion
// ---------------------------------------------------------------------------

function useStreaming(text, enabled) {
  const reduced = useMemo(() => prefersReducedMotion(), [])
  const active = enabled && !reduced
  const [count, setCount] = useState(active && text ? 0 : (text ? text.length : 0))

  useEffect(() => {
    if (!active || !text) {
      setCount(text ? text.length : 0)
      return
    }
    setCount(0)
    const step = Math.max(2, Math.ceil(text.length / 140)) // ~2.3s for 1000 chars
    const id = setInterval(() => {
      setCount((c) => {
        const next = Math.min(text.length, c + step)
        if (next >= text.length) clearInterval(id)
        return next
      })
    }, 16)
    return () => clearInterval(id)
  }, [text, active])

  return {
    shown: text ? text.slice(0, count) : '',
    done: !text || count >= text.length,
  }
}

// ---------------------------------------------------------------------------
// Source badges (dot + label, token source-badge component)
// ---------------------------------------------------------------------------

function SourceBadges({ citations }) {
  const kinds = useMemo(() => {
    const set = new Set()
    for (const c of citations || []) {
      if (c.type === 'docs') set.add('docs')
      else if (c.type === 'both') set.add('both')
      else set.add('customer')
    }
    return set
  }, [citations])

  if (kinds.size === 0) return null
  const badge = (key, label) => (
    <span key={key} className={`source-badge ${key}`}>
      <span className="source-badge-dot" />
      {label}
    </span>
  )
  return (
    <div className="source-badges">
      {kinds.has('both') && badge('both', 'customer data + live docs')}
      {kinds.has('customer') && !kinds.has('both') && badge('customer', 'customer data')}
      {kinds.has('docs') && !kinds.has('both') && badge('docs', 'live docs')}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Agent turn — the signature element: unboxed text + grounding thread
// ---------------------------------------------------------------------------

function AgentMessage({ msg, onProgress }) {
  const turnRef = useRef(null)
  const [expandedKey, setExpandedKey] = useState(null)
  const [mobileRailOpen, setMobileRailOpen] = useState(false)

  const { shown, done } = useStreaming(msg.answer, msg.streaming !== false)
  useEffect(() => {
    if (!done) onProgress?.()
  }, [shown, done, onProgress])

  const citMap = useMemo(() => new Map((msg.citations || []).map((c) => [c.id, c])), [msg.citations])
  const sources = useMemo(() => {
    const seen = new Map()
    for (const c of msg.citations || []) if (!seen.has(c.id)) seen.set(c.id, c)
    return [...seen.values()]
  }, [msg.citations])

  const html = useMemo(() => renderAnswer(shown, citMap, expandedKey), [shown, citMap, expandedKey])

  // Hover linking: one element sets .linked on all with the same data-src.
  const handleOver = useCallback((e) => {
    const el = e.target.closest('[data-src]')
    if (!el || !turnRef.current) return
    const key = el.dataset.src
    turnRef.current.querySelectorAll('[data-src]').forEach((n) => {
      n.classList.toggle('linked', n.dataset.src === key)
    })
  }, [])

  const handleOut = useCallback(() => {
    turnRef.current?.querySelectorAll('[data-src]').forEach((n) => n.classList.remove('linked'))
  }, [])

  const handleClick = useCallback((e) => {
    const el = e.target.closest('[data-src]')
    if (!el) return
    setExpandedKey((k) => (k === el.dataset.src ? null : el.dataset.src))
  }, [])

  const railEntry = (cit, expandable) => (
    <div key={cit.id} className={`rail-entry ${typeOf(cit)}`} data-src={cit.id}>
      <span className={`rail-dot ${typeOf(cit)}`} />
      <span className="rail-label-text">{railLabel(cit)}</span>
      {cit.stale && (
        <span className="stale-indicator" title="Live fetch failed — showing cached copy">
          <span className="stale-dot" />cached
        </span>
      )}
      {expandable && expandedKey === cit.id && (
        <div className="rail-detail" dangerouslySetInnerHTML={{ __html: detailMarkup(cit) }} />
      )}
    </div>
  )

  return (
    <div
      className={`agent-turn ${done ? 'revealed' : 'streaming'}`}
      ref={turnRef}
      onMouseOver={handleOver}
      onMouseOut={handleOut}
      onClick={handleClick}
    >
      {msg.contradictions?.length > 0 && (
        <div className="contradiction-banner" role="alert">
          <div className="banner-label">Contradiction detected</div>
          {msg.contradictions.map((c, i) => (
            <div key={i} className="banner-body">{c.analysis}</div>
          ))}
        </div>
      )}

      <div className="agent-row">
        <div className="sources-rail" aria-label="Sources for this answer">
          <div className="rail-label">Sources</div>
          {sources.length === 0 && <div className="rail-empty">none</div>}
          {sources.map((c) => railEntry(c, true))}
        </div>

        <div className="answer-area">
          <SourceBadges citations={msg.citations} />
          <div className="answer-text" dangerouslySetInnerHTML={{ __html: html }} />

          {msg.refused && (
            <div className="refusal-panel">
              <div className="refusal-title">Not enough information to answer this</div>
              <div className="refusal-sub">Here's what's related, if useful:</div>
              <ul className="refusal-list">
                {(msg.related || []).map((r) => (
                  <li key={r.id}>
                    <span className="refusal-id">{r.id}</span>
                    <span className="refusal-preview">{r.preview}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* Mobile: rail collapses into an expandable strip below the answer */}
      {sources.length > 0 && (
        <div className="mobile-rail">
          <button
            type="button"
            className="mobile-rail-toggle"
            onClick={() => setMobileRailOpen((o) => !o)}
            aria-expanded={mobileRailOpen}
          >
            <span className={`rail-caret ${mobileRailOpen ? 'open' : ''}`}>▸</span>
            Sources ({sources.length})
          </button>
          {mobileRailOpen && (
            <div className="mobile-rail-list">
              {sources.map((c) => railEntry(c, false))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPanel, setShowPanel] = useState(false)
  const [reindexBusy, setReindexBusy] = useState(false)
  const [reindexLog, setReindexLog] = useState(() => (USE_MOCK ? [...MOCK_REINDEX_SEED] : []))
  const [streamTick, setStreamTick] = useState(0)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const flowIdx = useRef(0)
  const reduced = useMemo(() => prefersReducedMotion(), [])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'end' })
  }, [messages, streamTick, busy, reduced])

  const appendAgent = useCallback((agentMsg) => {
    setMessages((prev) => [...prev, { role: 'agent', ...agentMsg }])
  }, [])

  const sendMock = useCallback(
    (question) => {
      if (busy) return
      setMessages((prev) => [...prev, { role: 'user', content: question }])
      setInput('')
      setBusy(true)
      setTimeout(() => {
        const state = MOCK_STATES[flowIdx.current % MOCK_STATES.length]
        flowIdx.current += 1
        appendAgent(state)
        setBusy(false)
      }, 800)
    },
    [busy, appendAgent]
  )

  const sendReal = useCallback(
    async (question) => {
      if (busy) return
      setMessages((prev) => [...prev, { role: 'user', content: question }])
      setInput('')
      setBusy(true)
      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question }),
        })
        if (!res.ok) {
          const err = await res.json()
          throw new Error(err.detail || 'Request failed')
        }
        const data = await res.json()
        const refused = /don'?t have enough information/i.test(data.answer || '')
        appendAgent({
          answer: data.answer,
          citations: data.citations || [],
          contradictions: data.contradictions || [],
          refused,
          related: refused
            ? (data.citations || []).slice(0, 3).map((c) => ({
                id: c.id,
                preview: (c.content_preview || '').slice(0, 140),
              }))
            : [],
        })
      } catch (err) {
        appendAgent({
          answer: `⚠️ ${err.message}`,
          citations: [],
          contradictions: [],
          refused: false,
        })
      } finally {
        setBusy(false)
      }
    },
    [busy, appendAgent]
  )

  const handleSend = useCallback(
    (e) => {
      e?.preventDefault()
      const q = input.trim()
      if (!q || busy) return
      if (USE_MOCK) sendMock(q)
      else sendReal(q)
    },
    [input, busy, sendMock, sendReal]
  )

  const previewState = useCallback(
    (state) => {
      if (state.userText) {
        setMessages((prev) => [...prev, { role: 'user', content: state.userText }])
      }
      appendAgent(state)
    },
    [appendAgent]
  )

  const runReindex = useCallback(async () => {
    if (reindexBusy) return
    setReindexBusy(true)
    if (USE_MOCK) {
      setTimeout(() => {
        setReindexLog((prev) => [...prev, mockReindexEvent()])
        setReindexBusy(false)
      }, 400)
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/reindex`, { method: 'POST' })
      const data = await res.json()
      const now = new Date().toLocaleTimeString('en-GB', { hour12: false })
      const msg =
        data.status === 'no_changes'
          ? 'delta-reindex: no changes detected — index up to date'
          : `delta-reindex: ${data.records_updated} records re-embedded · ${data.records_deleted} removed — files: ${(data.changed_files || []).join(', ')}`
      setReindexLog((prev) => [...prev, { time: now, msg }])
    } catch (err) {
      setReindexLog((prev) => [...prev, { time: new Date().toLocaleTimeString('en-GB', { hour12: false }), msg: `reindex failed: ${err.message}` }])
    } finally {
      setReindexBusy(false)
    }
  }, [reindexBusy])

  const onProgress = useCallback(() => setStreamTick((t) => t + 1), [])

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <span className="logo-icon">⬡</span>
          <span className="logo-text">Sanchalak A Cross-Source Knowledge Agent for Solutions Engineering</span>
        </div>
        <div className="header-right">
          {USE_MOCK && <span className="mock-flag">mock data</span>}
          <button
            type="button"
            className={`header-btn ${showPanel ? 'active' : ''}`}
            onClick={() => setShowPanel((o) => !o)}
          >
            Reindex log
          </button>
        </div>
      </header>

      <div className="main-layout">
        <main className="chat-container">
          <div className="messages">
            {messages.length === 0 && (
              <div className="welcome">
                <div className="welcome-mark">⬡</div>
                <h1 className="welcome-title">Ask about customers, docs, or both</h1>
                <p className="welcome-sub">
                  Every claim is traceable to a record ID or a docs page. Grounded answers carry
                  citation chips connected to a sources rail.
                </p>
                <div className="welcome-buttons">
                  <button type="button" className="btn-secondary" onClick={() => previewState(MOCK_STATES[0])}>
                    Grounded answer
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => previewState(MOCK_STATES[1])}>
                    Refusal
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => previewState(MOCK_STATES[2])}>
                    Cached fallback
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => previewState(MOCK_STATES[3])}>
                    Contradiction
                  </button>
                </div>
                {USE_MOCK && (
                  <p className="welcome-note">
                    Mock mode — set USE_MOCK = false in src/mockData.js to wire the live backend.
                  </p>
                )}
              </div>
            )}

            {messages.map((msg, i) =>
              msg.role === 'user' ? (
                <div key={i} className="message user">
                  <div className="chat-bubble-user">{msg.content}</div>
                </div>
              ) : (
                <div key={i} className="message agent">
                  <AgentMessage msg={msg} onProgress={onProgress} />
                </div>
              )
            )}

            {busy && (
              <div className="message agent">
                <div className="retrieving">
                  <span className="retrieving-dot" />
                  Retrieving from customer corpus and live docs…
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <form className="input-area" onSubmit={handleSend}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about customers, docs, or both…"
              disabled={busy}
            />
            <button type="submit" className="btn-primary" disabled={busy || !input.trim()}>
              Send
            </button>
          </form>
        </main>

        {showPanel && (
          <aside className="side-panel">
            <div className="panel-header">
              <h3 className="panel-title">Reindex log</h3>
              <button type="button" className="panel-close" onClick={() => setShowPanel(false)} aria-label="Close panel">
                ×
              </button>
            </div>
            <div className="panel-content">
              <p className="panel-hint">
                Edit a record in <code>dataset/</code>, then run delta reindex. Only changed records
                are re-embedded — the index updates incrementally.
              </p>
              <button type="button" className="reindex-run" onClick={runReindex} disabled={reindexBusy}>
                {reindexBusy ? 'Running…' : 'Run Delta Reindex'}
              </button>
              <div className="reindex-log-panel">
                {reindexLog.length === 0 && <div className="log-empty">No reindex operations yet.</div>}
                {reindexLog.map((e, i) => (
                  <div key={i} className="log-entry">
                    <span className="log-time">{e.time}</span>
                    <span className="log-msg">{e.msg}</span>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}

export default App
