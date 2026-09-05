import { useState, useEffect, useRef } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { fetchJob, deleteJob, retryJob, createSSEConnection } from '../api'

const STEPS = [
  { key: 'download', label: 'Download' },
  { key: 'transcribe', label: 'Transcribe' },
  { key: 'analyze', label: 'AI Analysis' },
  { key: 'metadata', label: 'Metadata' },
  { key: 'render', label: 'Render' },
  { key: 'done', label: 'Done' },
]

function parseLogLine(line) {
  // Matches e.g. [17:15:22] [AI_RETRY] message or [download] message
  const match = line.match(/^(\[\d{2}:\d{2}:\d{2}\])?\s*\[([a-zA-Z0-9_-]+)\]\s*(.*)$/)
  if (match) {
    return {
      time: match[1] ? match[1].replace(/[\[\]]/g, '') : null,
      badge: match[2].toUpperCase(),
      message: match[3],
    }
  }
  return { time: null, badge: 'INFO', message: line }
}

function JobDetail() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [retryCount, setRetryCount] = useState(0)

  // Log Stream Controls
  const [logFilter, setLogFilter] = useState('all') // 'all' | 'ai' | 'errors'
  const [logSearch, setLogSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [copied, setCopied] = useState(false)
  const logEndRef = useRef(null)

  const handleDelete = async () => {
    if (!window.confirm(`Are you sure you want to delete job #${jobId}?`)) return
    setDeleting(true)
    try {
      await deleteJob(jobId)
      navigate('/')
    } catch (err) {
      alert('Failed to delete job: ' + err.message)
      setDeleting(false)
    }
  }

  const handleRetry = async () => {
    if (!window.confirm(`Retry job #${jobId} now?`)) return
    setRetrying(true)
    try {
      const updated = await retryJob(jobId)
      setJob(updated)
      setRetryCount(c => c + 1)
    } catch (err) {
      alert('Failed to retry job: ' + err.message)
    } finally {
      setRetrying(false)
    }
  }

  const handleCopyLogs = () => {
    if (!job?.log) return
    const text = job.log.join('\n')
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  useEffect(() => {
    let sse = null

    const load = async () => {
      try {
        const data = await fetchJob(jobId)
        setJob(data)

        const terminal = ['completed', 'failed', 'cancelled']
        if (!terminal.includes(data.status)) {
          sse = createSSEConnection(jobId, (event) => {
            if (event.type === 'completed') {
              fetchJob(jobId).then(setJob)
            } else if (event.type === 'progress') {
              setJob(prev => prev ? {
                ...prev,
                status: event.status,
                progress: event.progress,
                error: event.error,
                log: event.log || prev.log,
                ai_diagnostics: event.ai_diagnostics || prev.ai_diagnostics,
              } : prev)
            }
          })
        }
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    load()
    return () => { if (sse) sse.close() }
  }, [jobId, retryCount])

  // Polling fallback
  useEffect(() => {
    if (!job) return
    const terminal = ['completed', 'failed', 'cancelled']
    if (terminal.includes(job.status)) return

    const interval = setInterval(async () => {
      try {
        const data = await fetchJob(jobId)
        setJob(data)
      } catch {}
    }, 3000)
    return () => clearInterval(interval)
  }, [jobId, job?.status, retryCount])

  // Auto-scroll log
  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [job?.log?.length, autoScroll, logFilter, logSearch])

  if (loading) return <div className="empty-state"><div className="spinner"></div></div>
  if (!job) return <div className="empty-state"><h3>Job not found</h3></div>

  const currentStep = job.progress?.step || ''
  const percent = job.progress?.percent || 0
  const aiDiag = job.ai_diagnostics || {}
  const aiProvider = aiDiag.provider || job.config?.ai_provider || 'gemini'
  const aiModel = aiDiag.model || job.config?.[`${aiProvider}_model`] || job.config?.ai_model || 'gemini-3.6-flash'
  const aiStatus = aiDiag.status || (currentStep === 'analyze' ? 'querying' : (job.status === 'completed' ? 'success' : 'idle'))

  // Filter logs
  const logs = job.log || []
  const filteredLogs = logs.filter(line => {
    const lower = line.toLowerCase()
    if (logSearch && !lower.includes(logSearch.toLowerCase())) return false
    if (logFilter === 'ai') {
      return lower.includes('[ai') || lower.includes('gemini') || lower.includes('sambanova') || lower.includes('nvidia') || lower.includes('whisper')
    }
    if (logFilter === 'errors') {
      return lower.includes('gagal') || lower.includes('fail') || lower.includes('error') || lower.includes('retry') || lower.includes('warn') || lower.includes('404') || lower.includes('429') || lower.includes('402') || lower.includes('fallback')
    }
    return true
  })

  return (
    <div className="fade-in">
      <div className="page-header">
        <div>
          <h2>Job #{job.id}</h2>
          <p>{job.url || job.upload_filename || 'Unknown source'}</p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <span className={`badge badge-${job.status}`}>{job.status}</span>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={retrying}
            title={['completed', 'failed', 'cancelled'].includes(job.status) ? "Retry this job" : "Restart / Force retry this job"}
            onClick={handleRetry}
          >
            {retrying ? 'Retrying...' : '🔄 Retry'}
          </button>
          <Link to="/new" state={{ reuseJob: job }} className="btn btn-secondary btn-sm">🔁 Clone & Rerun</Link>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            disabled={deleting}
            onClick={handleDelete}
          >
            {deleting ? 'Deleting...' : '🗑️ Delete'}
          </button>
          <Link to="/" className="btn btn-ghost btn-sm">← Back</Link>
        </div>
      </div>

      {/* Progress */}
      {!['completed', 'failed', 'cancelled'].includes(job.status) && (
        <div className="card" style={{ marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '13px', fontWeight: 600 }}>Progress</span>
            <span style={{ fontSize: '13px', color: 'var(--accent-hover)' }}>{Math.round(percent)}%</span>
          </div>
          <div className="progress-bar-bg">
            <div className="progress-bar-fill" style={{ width: `${percent}%` }}></div>
          </div>
          {job.progress?.message && (
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '10px' }}>
              {job.progress.message}
            </p>
          )}
          <div className="progress-steps" style={{ marginTop: '14px' }}>
            {STEPS.map(s => {
              const stepIdx = STEPS.findIndex(x => x.key === s.key)
              const currentIdx = STEPS.findIndex(x => x.key === currentStep)
              let cls = ''
              if (stepIdx < currentIdx) cls = 'done'
              else if (stepIdx === currentIdx) cls = 'active'
              return (
                <div key={s.key} className={`progress-step ${cls}`}>
                  <span className="step-dot"></span>
                  {s.label}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* AI Model Health & Diagnostics Card */}
      {(currentStep === 'analyze' || aiDiag.status || aiDiag.last_error || job.status === 'failed') && (
        <div className={`ai-diagnostics-card status-${aiStatus}`}>
          <div className="ai-diag-header">
            <div className="ai-diag-title">
              <span style={{ fontSize: '18px' }}>
                {aiProvider === 'sambanova' ? '⚡' : aiProvider === 'nvidia' ? '🟢' : '💎'}
              </span>
              <h4>AI Engine: {aiProvider.toUpperCase()}</h4>
              <span className="ai-model-tag">{aiModel}</span>
              {aiDiag.fallback_model && (
                <span className="ai-model-tag" style={{ borderColor: 'rgba(249, 115, 22, 0.4)', color: '#fb923c' }}>
                  Fallback: {aiDiag.fallback_model}
                </span>
              )}
            </div>

            <div className={`ai-status-pill status-${aiStatus}`}>
              {['querying', 'retrying', 'fallback'].includes(aiStatus) && <span className="ai-pulse-dot"></span>}
              {aiStatus === 'querying' && 'Querying Model...'}
              {aiStatus === 'retrying' && `Retrying (Attempt ${aiDiag.attempt || 1}/${aiDiag.max_attempts || 3})`}
              {aiStatus === 'degraded' && 'Performance Degraded'}
              {aiStatus === 'fallback' && 'Fallback Engaged'}
              {aiStatus === 'failed' && 'Model Failed'}
              {aiStatus === 'success' && 'Optimal & Ready'}
              {aiStatus === 'idle' && 'Standby'}
            </div>
          </div>

          <div className="ai-stats-row">
            <div className="ai-stat-item">
              <span className="ai-stat-label">Status</span>
              <span className="ai-stat-value" style={{ textTransform: 'capitalize' }}>
                {aiStatus}
              </span>
            </div>

            {aiDiag.attempt && (
              <div className="ai-stat-item">
                <span className="ai-stat-label">Attempt</span>
                <span className="ai-stat-value">{aiDiag.attempt} / {aiDiag.max_attempts || 3}</span>
              </div>
            )}

            {aiDiag.elapsed_seconds && (
              <div className="ai-stat-item">
                <span className="ai-stat-label">Latency</span>
                <span className="ai-stat-value">{aiDiag.elapsed_seconds}s</span>
              </div>
            )}

            {aiDiag.retry_in_seconds > 0 && (
              <div className="ai-stat-item">
                <span className="ai-stat-label">Backoff Delay</span>
                <span className="ai-stat-value" style={{ color: 'var(--warning)' }}>{aiDiag.retry_in_seconds}s</span>
              </div>
            )}

            {aiDiag.clips_found !== undefined && (
              <div className="ai-stat-item">
                <span className="ai-stat-label">Clips Extracted</span>
                <span className="ai-stat-value" style={{ color: 'var(--success)' }}>{aiDiag.clips_found}</span>
              </div>
            )}
          </div>

          {/* Actionable Resolution Guidance */}
          {(['retrying', 'degraded', 'fallback', 'failed'].includes(aiStatus) || aiDiag.last_error) && (
            <div className={`ai-resolution-box ${aiStatus === 'failed' ? '' : 'warning-box'}`}>
              <strong>
                {aiStatus === 'failed' ? '❌ AI Model Failed' : '⚠️ AI Model Warning / Degradation Detected'}
                {aiDiag.last_status_code ? ` [HTTP ${aiDiag.last_status_code}]` : ''}
              </strong>
              <div>{aiDiag.last_error || 'The AI model experienced connection or quota issues.'}</div>
              {aiDiag.resolution_hint && (
                <div style={{ marginTop: '6px', fontWeight: 500, color: 'var(--text-primary)' }}>
                  💡 <strong>How to resolve:</strong> {aiDiag.resolution_hint}
                </div>
              )}
              <div style={{ marginTop: '10px', display: 'flex', gap: '8px' }}>
                <Link to="/settings" className="btn btn-secondary btn-sm" style={{ padding: '3px 10px', fontSize: '11px' }}>
                  ⚙️ Configure API Keys
                </Link>
                <Link to="/new" state={{ reuseJob: job }} className="btn btn-ghost btn-sm" style={{ padding: '3px 10px', fontSize: '11px' }}>
                  Switch Provider in New Job
                </Link>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {job.error && (
        <div className="card" style={{ marginBottom: '16px', borderColor: 'rgba(239,68,68,0.2)' }}>
          <h3 style={{ color: 'var(--error)', fontSize: '14px', marginBottom: '8px' }}>❌ Pipeline Error</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{job.error}</p>
        </div>
      )}

      {/* Clips */}
      {job.clips && job.clips.length > 0 && (
        <>
          <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '16px' }}>
            🎞️ Generated Clips ({job.clips.length})
          </h3>
          <div className="clip-grid">
            {job.clips.map((clip, i) => (
              <div key={i} className="clip-card">
                <video className="clip-video" controls preload="metadata" src={clip.download_url} />
                <div className="clip-body">
                  <div className="clip-title">{clip.title_en || clip.title || `Clip ${clip.rank}`}</div>
                  <div className="clip-stats">
                    {clip.viral_score && <span className="viral-score">🔥 {clip.viral_score}</span>}
                    {clip.duration && <span>{Math.round(clip.duration)}s</span>}
                    <span>Rank #{clip.rank}</span>
                  </div>
                  <div className="clip-actions">
                    <a href={clip.download_url} download className="btn btn-secondary btn-sm">⬇️ Download</a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Real-time Streaming Activity Log */}
      <div className="log-stream-card">
        <div className="log-stream-header">
          <div className="log-filter-tabs">
            <button
              type="button"
              className={`log-tab-btn ${logFilter === 'all' ? 'active' : ''}`}
              onClick={() => setLogFilter('all')}
            >
              All Logs ({logs.length})
            </button>
            <button
              type="button"
              className={`log-tab-btn ${logFilter === 'ai' ? 'active' : ''}`}
              onClick={() => setLogFilter('ai')}
            >
              🤖 AI Diagnostics
            </button>
            <button
              type="button"
              className={`log-tab-btn ${logFilter === 'errors' ? 'active' : ''}`}
              onClick={() => setLogFilter('errors')}
            >
              ⚠️ Warnings & Errors
            </button>
          </div>

          <div className="log-stream-actions">
            <input
              type="text"
              className="log-search-input"
              placeholder="Search logs..."
              value={logSearch}
              onChange={(e) => setLogSearch(e.target.value)}
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              Auto-scroll
            </label>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={handleCopyLogs}
              title="Copy entire log to clipboard"
            >
              {copied ? '✅ Copied' : '📋 Copy Logs'}
            </button>
          </div>
        </div>

        <div className="log-viewer">
          {filteredLogs.length === 0 ? (
            <div style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', padding: '8px 0' }}>
              No log entries match the current filter.
            </div>
          ) : (
            filteredLogs.map((rawLine, i) => {
              const { time, badge, message } = parseLogLine(rawLine)
              return (
                <div key={i} className="log-row">
                  {time && <span className="log-time">{time}</span>}
                  <span className={`log-badge badge-${badge.toLowerCase()}`}>
                    {badge}
                  </span>
                  <span className="log-text">{message}</span>
                </div>
              )
            })
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  )
}

export default JobDetail
