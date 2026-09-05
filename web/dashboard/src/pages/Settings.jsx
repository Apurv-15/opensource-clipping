import { useState, useEffect } from 'react'
import { fetchSettings, updateSettings } from '../api'

const PasswordInput = ({ value, onChange, placeholder, isSet }) => {
  const [show, setShow] = useState(false)
  return (
    <div style={{ position: 'relative' }}>
      <input
        className="form-input"
        type={show ? "text" : "password"}
        placeholder={isSet ? '••••••••••••••••' : placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ paddingRight: '40px' }}
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        style={{
          position: 'absolute',
          right: '12px',
          top: '50%',
          transform: 'translateY(-50%)',
          background: 'none',
          border: 'none',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          fontSize: '14px',
          padding: '4px'
        }}
        title={show ? "Hide" : "Show"}
      >
        {show ? '👀' : '👁️'}
      </button>
    </div>
  )
}

function Settings() {
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const [googleKey, setGoogleKey] = useState('')
  const [sambanovaKey, setSambanovaKey] = useState('')
  const [pexelsKey, setPexelsKey] = useState('')
  const [hfToken, setHfToken] = useState('')
  const [nvidiaKey, setNvidiaKey] = useState('')

  // Duration & Clipping rate defaults
  const [minClipDuration, setMinClipDuration] = useState(20)
  const [maxClipDuration, setMaxClipDuration] = useState(90)
  const [defaultClips, setDefaultClips] = useState(7)

  useEffect(() => {
    fetchSettings()
      .then(data => {
        setSettings(data)
        if (data?.default_min_clip_duration !== undefined) setMinClipDuration(data.default_min_clip_duration)
        if (data?.default_max_clip_duration !== undefined) setMaxClipDuration(data.default_max_clip_duration)
        if (data?.default_clips !== undefined) setDefaultClips(data.default_clips)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setMsg('')
    try {
      const payload = {}
      if (googleKey) payload.google_api_key = googleKey
      if (sambanovaKey) payload.sambanova_api_key = sambanovaKey
      if (pexelsKey) payload.pexels_api_key = pexelsKey
      if (hfToken) payload.hf_token = hfToken
      if (nvidiaKey) payload.nvidia_api_key = nvidiaKey

      const minDurNum = parseInt(minClipDuration, 10)
      const maxDurNum = parseInt(maxClipDuration, 10)
      const clipsNum = parseInt(defaultClips, 10)

      if (!isNaN(minDurNum) && minDurNum !== settings?.default_min_clip_duration) {
        payload.default_min_clip_duration = minDurNum
      }
      if (!isNaN(maxDurNum) && maxDurNum !== settings?.default_max_clip_duration) {
        payload.default_max_clip_duration = maxDurNum
      }
      if (!isNaN(clipsNum) && clipsNum !== settings?.default_clips) {
        payload.default_clips = clipsNum
      }

      if (Object.keys(payload).length === 0) {
        setMsg('No changes made')
        setSaving(false)
        return
      }

      const updated = await updateSettings(payload)
      setSettings(updated)
      if (updated?.default_min_clip_duration !== undefined) setMinClipDuration(updated.default_min_clip_duration)
      if (updated?.default_max_clip_duration !== undefined) setMaxClipDuration(updated.default_max_clip_duration)
      if (updated?.default_clips !== undefined) setDefaultClips(updated.default_clips)

      setGoogleKey('')
      setSambanovaKey('')
      setPexelsKey('')
      setHfToken('')
      setNvidiaKey('')
      setMsg('✅ Settings updated successfully!')
    } catch (err) {
      setMsg('❌ Failed to save: ' + err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="empty-state"><div className="spinner"></div></div>

  return (
    <div className="fade-in">
      <div className="page-header">
        <div>
          <h2>Settings</h2>
          <p>Configure API keys and default clipping settings</p>
        </div>
      </div>

      <form onSubmit={handleSave}>
        <div className="settings-grid">
          {/* API Keys */}
          <div className="settings-section">
            <h3>🔑 API Keys</h3>

            <div className="form-group">
              <label className="form-label">
                Google Gemini API Key
                {settings?.google_api_key_set && <span style={{ color: 'var(--success)', marginLeft: '8px' }}>✅ Set</span>}
              </label>
              <PasswordInput
                value={googleKey}
                onChange={setGoogleKey}
                placeholder="Paste your Gemini API key"
                isSet={settings?.google_api_key_set}
              />
              <p className="form-hint">
                <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener" style={{ color: 'var(--accent)' }}>Get free key →</a>
              </p>
            </div>

            <div className="form-group">
              <label className="form-label">
                Pexels API Key
                {settings?.pexels_api_key_set && <span style={{ color: 'var(--success)', marginLeft: '8px' }}>✅ Set</span>}
              </label>
              <PasswordInput
                value={pexelsKey}
                onChange={setPexelsKey}
                placeholder="For B-roll footage (optional)"
                isSet={settings?.pexels_api_key_set}
              />
              <p className="form-hint">Required for B-roll stock footage</p>
            </div>

            <div className="form-group">
              <label className="form-label">
                HuggingFace Token
                {settings?.hf_token_set && <span style={{ color: 'var(--success)', marginLeft: '8px' }}>✅ Set</span>}
              </label>
              <PasswordInput
                value={hfToken}
                onChange={setHfToken}
                placeholder="For split-screen mode (optional)"
                isSet={settings?.hf_token_set}
              />
              <p className="form-hint">Required for speaker diarization</p>
            </div>

            <div className="form-group">
              <label className="form-label">
                SambaNova API Key (Free)
                {settings?.sambanova_api_key_set && <span style={{ color: 'var(--success)', marginLeft: '8px' }}>✅ Set</span>}
              </label>
              <PasswordInput
                value={sambanovaKey}
                onChange={setSambanovaKey}
                placeholder="Paste your free SambaNova API key"
                isSet={settings?.sambanova_api_key_set}
              />
              <p className="form-hint">
                <a href="https://cloud.sambanova.ai/" target="_blank" rel="noopener" style={{ color: 'var(--accent)' }}>Get free key →</a>
              </p>
            </div>

            <div className="form-group">
              <label className="form-label">
                NVIDIA API Key
                {settings?.nvidia_api_key_set && <span style={{ color: 'var(--success)', marginLeft: '8px' }}>✅ Set</span>}
              </label>
              <PasswordInput
                value={nvidiaKey}
                onChange={setNvidiaKey}
                placeholder="For NVIDIA NIM provider (optional)"
                isSet={settings?.nvidia_api_key_set}
              />
            </div>
          </div>

          {/* Clip Duration & Virality Strategy */}
          <div className="settings-section">
            <h3>⏱️ Clip Duration & Virality Rate</h3>
            <p className="form-hint" style={{ marginBottom: '14px' }}>
              Configure clip duration to optimize audience retention rate and algorithms for TikTok/Reels/Shorts. Shorter durations (20–60s) are proven to achieve significantly higher completion rates.
            </p>

            {/* Quick Presets */}
            <div style={{ marginBottom: '16px' }}>
              <label className="form-label" style={{ marginBottom: '8px' }}>Select Strategy Preset</label>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '8px' }}>
                <button
                  type="button"
                  className={`btn btn-sm ${minClipDuration === 20 && maxClipDuration === 60 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(20); setMaxClipDuration(60) }}
                  style={{ textAlign: 'left', padding: '8px 10px', fontSize: '12px' }}
                >
                  <div style={{ fontWeight: '600' }}>⚡ Viral Shorts</div>
                  <div style={{ opacity: 0.8, fontSize: '11px' }}>20s – 60s (Top Retention)</div>
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${minClipDuration === 30 && maxClipDuration === 90 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(30); setMaxClipDuration(90) }}
                  style={{ textAlign: 'left', padding: '8px 10px', fontSize: '12px' }}
                >
                  <div style={{ fontWeight: '600' }}>📈 Balanced Story</div>
                  <div style={{ opacity: 0.8, fontSize: '11px' }}>30s – 90s (Reels / Flow)</div>
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${minClipDuration === 15 && maxClipDuration === 45 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(15); setMaxClipDuration(45) }}
                  style={{ textAlign: 'left', padding: '8px 10px', fontSize: '12px' }}
                >
                  <div style={{ fontWeight: '600' }}>🔥 Snappy Hook</div>
                  <div style={{ opacity: 0.8, fontSize: '11px' }}>15s – 45s (Fast Punch)</div>
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${minClipDuration === 60 && maxClipDuration === 180 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(60); setMaxClipDuration(180) }}
                  style={{ textAlign: 'left', padding: '8px 10px', fontSize: '12px' }}
                >
                  <div style={{ fontWeight: '600' }}>🎙️ Deep Dive</div>
                  <div style={{ opacity: 0.8, fontSize: '11px' }}>60s – 180s (Podcast)</div>
                </button>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Min Clip Duration (seconds)</label>
                <input
                  className="form-input"
                  type="number"
                  min="10"
                  max="300"
                  value={minClipDuration}
                  onChange={(e) => setMinClipDuration(e.target.value)}
                  placeholder="20"
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Max Clip Duration (seconds)</label>
                <input
                  className="form-input"
                  type="number"
                  min="15"
                  max="600"
                  value={maxClipDuration}
                  onChange={(e) => setMaxClipDuration(e.target.value)}
                  placeholder="90"
                />
              </div>
            </div>

            {parseInt(minClipDuration, 10) >= parseInt(maxClipDuration, 10) && (
              <p style={{ color: 'var(--warning)', fontSize: '12px', marginBottom: '12px' }}>
                ⚠️ Min duration must be less than Max duration.
              </p>
            )}

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Default Target Number of Clips</label>
              <input
                className="form-input"
                type="number"
                min="1"
                max="30"
                value={defaultClips}
                onChange={(e) => setDefaultClips(e.target.value)}
                placeholder="7"
              />
              <p className="form-hint">Default number of candidate clips generated per video processing job.</p>
            </div>
          </div>

          {/* System Info */}
          <div className="settings-section">
            <h3>💻 System Info</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>GPU</span>
                <span style={{ color: settings?.gpu_available ? 'var(--success)' : 'var(--text-tertiary)' }}>
                  {settings?.gpu_available ? '✅ Available' : '⚪ Not available'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Default Whisper</span>
                <span>{settings?.default_whisper_model}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Default AI</span>
                <span>{settings?.default_ai_provider}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Default Ratio</span>
                <span>{settings?.default_ratio}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Target Clip Duration</span>
                <span style={{ color: 'var(--accent)' }}>
                  {settings?.default_min_clip_duration || 20}s – {settings?.default_max_clip_duration || 90}s
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Default Clip Count</span>
                <span>{settings?.default_clips || 7} clips</span>
              </div>
            </div>
          </div>
        </div>

        {msg && (
          <div style={{ marginTop: '16px', fontSize: '13px', color: msg.startsWith('✅') ? 'var(--success)' : 'var(--error)' }}>
            {msg}
          </div>
        )}

        <button type="submit" className="btn btn-primary" disabled={saving} style={{ marginTop: '20px' }}>
          {saving ? <><span className="spinner"></span> Saving...</> : '💾 Save Settings'}
        </button>
      </form>
    </div>
  )
}

export default Settings
