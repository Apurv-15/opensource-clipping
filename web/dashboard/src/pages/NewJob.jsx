import { useState, useRef, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { createJob, uploadVideo, fetchSettings } from '../api'

function NewJob() {
  const navigate = useNavigate()
  const location = useLocation()
  const fileRef = useRef(null)

  const [mode, setMode] = useState('url') // 'url' or 'upload'
  const [url, setUrl] = useState('')
  const [uploadFilename, setUploadFilename] = useState('')
  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [reuseJobId, setReuseJobId] = useState('')

  // Config
  const [clips, setClips] = useState(7)
  const [minClipDuration, setMinClipDuration] = useState(20)
  const [maxClipDuration, setMaxClipDuration] = useState(90)
  const [ratio, setRatio] = useState('9:16')
  const [source, setSource] = useState('youtube')
  const [fontStyle, setFontStyle] = useState('HORMOZI')
  const [whisperModel, setWhisperModel] = useState('base')
  const [whisperDevice, setWhisperDevice] = useState('cpu')
  const [aiProvider, setAiProvider] = useState('sambanova')
  const [aiModel, setAiModel] = useState('Meta-Llama-3.3-70B-Instruct')
  const [targetLanguage, setTargetLanguage] = useState('english')

  const PROVIDER_MODELS = {
    sambanova: [
      { id: 'Meta-Llama-3.3-70B-Instruct', name: 'Meta Llama 3.3 70B (Recommended)' },
      { id: 'DeepSeek-R1', name: 'DeepSeek R1 (Reasoning / Virality)' },
      { id: 'DeepSeek-V3.1', name: 'DeepSeek V3.1' },
      { id: 'Qwen2.5-72B-Instruct', name: 'Qwen 2.5 72B' },
      { id: 'Meta-Llama-3.1-8B-Instruct', name: 'Meta Llama 3.1 8B (Ultra Fast)' },
    ],
    gemini: [
      { id: 'gemini-3.6-flash', name: 'Gemini 3.6 Flash (Recommended)' },
      { id: 'gemini-3.7-flash', name: 'Gemini 3.7 Flash' },
      { id: 'gemini-3.8-flash', name: 'Gemini 3.8 Flash' },
      { id: 'gemini-3-flash-preview', name: 'Gemini 3 Flash Preview' },
    ],
    nvidia: [
      { id: 'deepseek-ai/deepseek-v4-pro', name: 'DeepSeek V4 Pro' },
      { id: 'meta/llama-3.3-70b-instruct', name: 'Meta Llama 3.3 70B' },
      { id: 'mistralai/mistral-large-2-instruct', name: 'Mistral Large 2' },
    ],
  }

  // Toggles
  const [useBroll, setUseBroll] = useState(true)
  const [useHookGlitch, setUseHookGlitch] = useState(true)
  const [useBgm, setUseBgm] = useState(true)
  const [useKaraoke, setUseKaraoke] = useState(true)
  const [textBehindPerson, setTextBehindPerson] = useState(false)
  const [useSplitScreen, setUseSplitScreen] = useState(false)
  const [useDynamicSplit, setUseDynamicSplit] = useState(true)
  const [splitAutoZoom, setSplitAutoZoom] = useState(true)
  const [useCameraSwitch, setUseCameraSwitch] = useState(false)
  const [noSubs, setNoSubs] = useState(false)
  const [hookV2, setHookV2] = useState(false)
  const [silenceTrim, setSilenceTrim] = useState(false)
  const [useDlpSubs, setUseDlpSubs] = useState(false)
  const [loadGeminiJson, setLoadGeminiJson] = useState(false)

  // Load settings default on mount
  useEffect(() => {
    fetchSettings()
      .then((settings) => {
        if (!location.state?.reuseJob) {
          if (settings?.default_min_clip_duration !== undefined) setMinClipDuration(settings.default_min_clip_duration)
          if (settings?.default_max_clip_duration !== undefined) setMaxClipDuration(settings.default_max_clip_duration)
          if (settings?.default_clips !== undefined) setClips(settings.default_clips)
        }
      })
      .catch(() => {})
  }, [location.state])

  // Load from location state if user clicked "Clone / Rerun"
  useEffect(() => {
    const reuseJob = location.state?.reuseJob
    if (reuseJob) {
      setReuseJobId(reuseJob.id)
      setUrl(reuseJob.url || '')
      setUploadFilename(reuseJob.upload_filename || '')
      setMode('reuse')
      setSource(reuseJob.source || 'youtube')
      
      const config = reuseJob.config || {}
      if (config.clips !== undefined) setClips(config.clips)
      if (config.min_clip_duration !== undefined) setMinClipDuration(config.min_clip_duration)
      if (config.max_clip_duration !== undefined) setMaxClipDuration(config.max_clip_duration)
      if (config.ratio !== undefined) setRatio(config.ratio)
      if (config.font_style !== undefined) setFontStyle(config.font_style)
      if (config.whisper_model !== undefined) setWhisperModel(config.whisper_model)
      if (config.whisper_device !== undefined) setWhisperDevice(config.whisper_device)
      if (config.ai_provider !== undefined) setAiProvider(config.ai_provider)
      
      if (config.use_broll !== undefined) setUseBroll(config.use_broll)
      if (config.use_hook_glitch !== undefined) setUseHookGlitch(config.use_hook_glitch)
      if (config.use_auto_bgm !== undefined) setUseBgm(config.use_auto_bgm)
      if (config.use_karaoke_effect !== undefined) setUseKaraoke(config.use_karaoke_effect)
      if (config.use_split_screen !== undefined) setUseSplitScreen(config.use_split_screen)
      if (config.use_camera_switch !== undefined) setUseCameraSwitch(config.use_camera_switch)
      if (config.hook_v2 !== undefined) setHookV2(config.hook_v2)
      if (config.silence_trim !== undefined) setSilenceTrim(config.silence_trim)
      if (config.use_dlp_subs !== undefined) setUseDlpSubs(config.use_dlp_subs)
      if (config.no_subs !== undefined) setNoSubs(config.no_subs)
      
      // Default to true when cloning to save AI tokens, user can untoggle
      setLoadGeminiJson(true)
    }
  }, [location.state])

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    setError('')
    try {
      const result = await uploadVideo(file)
      setUploadFilename(result.filename)
      setMode('upload')
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    let cleanUrl = url.trim()
    if (cleanUrl) {
      cleanUrl = cleanUrl.replace(/^https?:\/+/i, 'https://')
      if (cleanUrl.startsWith('www.')) {
        cleanUrl = 'https://' + cleanUrl
      }
    }

    if (mode === 'url' && !cleanUrl) {
      setError('Please enter a video URL first.')
      return
    }
    if (mode === 'upload' && !uploadFilename) {
      setError('Please select or upload a video file first.')
      return
    }
    if (mode === 'reuse' && !reuseJobId.trim()) {
      setError('Job ID cannot be empty')
      return
    }

    setSubmitting(true)
    try {
      const payload = {
        url: mode === 'url' ? cleanUrl : null,
        upload_filename: mode === 'upload' ? uploadFilename : null,
        source,
        clips: parseInt(clips, 10),
        min_clip_duration: parseInt(minClipDuration, 10) || 20,
        max_clip_duration: parseInt(maxClipDuration, 10) || 90,
        ratio,
        font_style: fontStyle,
        whisper_model: whisperModel,
        whisper_device: whisperDevice,
        whisper_compute_type: whisperDevice === 'cuda' ? 'float16' : 'int8',
        ai_provider: aiProvider,
        ai_model: aiModel,
        target_language: targetLanguage,
        use_broll: useBroll,
        use_hook_glitch: useHookGlitch,
        use_auto_bgm: useBgm,
        use_karaoke_effect: useKaraoke,
        text_behind_person: textBehindPerson,
        use_split_screen: useSplitScreen,
        use_dynamic_split: useDynamicSplit,
        split_auto_zoom: splitAutoZoom,
        split_trigger: useDynamicSplit ? 'face' : 'diarization',
        split_max_zoom: 1.5,
        use_camera_switch: useCameraSwitch,
        no_subs: noSubs,
        hook_v2: hookV2,
        silence_trim: silenceTrim,
        use_dlp_subs: useDlpSubs,
        load_gemini_json: loadGeminiJson,
        ...(reuseJobId.trim() ? { reuse_job_id: reuseJobId.trim() } : {}),
      }

      const job = await createJob(payload)
      navigate(`/job/${job.id}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fade-in">
      <div className="page-header">
        <div>
          <h2>New Clipping Job</h2>
          <p>Generate viral short clips from long-form videos</p>
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        {/* Source Selection */}
        <div className="card" style={{ marginBottom: '16px' }}>
          <h3 className="card-title" style={{ marginBottom: '16px' }}>📥 Video Source</h3>

          {/* Mode toggle */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <button
              type="button"
              className={`btn ${mode === 'url' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
              onClick={() => setMode('url')}
            >
              🔗 From URL
            </button>
            <button
              type="button"
              className={`btn ${mode === 'upload' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
              onClick={() => setMode('upload')}
            >
              📁 Upload File
            </button>
            <button
              type="button"
              className={`btn ${mode === 'reuse' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
              onClick={() => setMode('reuse')}
            >
              🔁 Reuse Job
            </button>
          </div>

          {mode === 'url' && (
            <>
              <div className="form-group">
                <label className="form-label">Video URL</label>
                <input
                  className="form-input"
                  type="url"
                  placeholder="https://www.youtube.com/watch?v=..."
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                <p className="form-hint">Mendukung YouTube, TikTok, Instagram, Google Drive</p>
              </div>
              <div className="form-group" style={{ maxWidth: '200px' }}>
                <label className="form-label">Platform</label>
                <select className="form-select" value={source} onChange={(e) => setSource(e.target.value)}>
                  <option value="youtube">YouTube</option>
                  <option value="tiktok">TikTok</option>
                  <option value="instagram">Instagram</option>
                  <option value="gdrive">Google Drive</option>
                </select>
              </div>
            </>
          )}

          {mode === 'upload' && (
            <div className="form-group">
              <label className="form-label">Upload Video</label>
              {uploadFilename ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ color: 'var(--success)' }}>✅ {uploadFilename}</span>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setUploadFilename(''); fileRef.current?.click() }}>
                    Change
                  </button>
                </div>
              ) : (
                <div>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="video/*"
                    onChange={handleFileUpload}
                    style={{ display: 'none' }}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => fileRef.current?.click()}
                    disabled={uploading}
                  >
                    {uploading ? <><span className="spinner"></span> Uploading...</> : '📁 Select Video File'}
                  </button>
                  <p className="form-hint">MP4, MKV, AVI, MOV, WebM (max 2GB)</p>
                </div>
              )}
            </div>
          )}

          {mode === 'reuse' && (
            <div className="form-group">
              <label className="form-label">Reuse Job ID</label>
              <input
                className="form-input"
                type="text"
                placeholder="Example: d20b47341e08"
                value={reuseJobId}
                onChange={(e) => setReuseJobId(e.target.value)}
              />
              <p className="form-hint" style={{ marginTop: '4px' }}>Bypass download using previous job ID. (If using Clone & Rerun, leave this field as is).</p>
            </div>
          )}
        </div>

        {/* Main Config */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px', marginBottom: '16px' }}>
          {/* Basic Settings */}
          <div className="config-section">
            <h4>🎯 Basic Settings</h4>
            <div className="form-group">
              <label className="form-label">Number of Clips</label>
              <input className="form-input" type="number" min="1" max="30" value={clips} onChange={(e) => setClips(parseInt(e.target.value) || 7)} />
            </div>
            <div className="form-group">
              <label className="form-label">Aspect Ratio</label>
              <select className="form-select" value={ratio} onChange={(e) => setRatio(e.target.value)}>
                <option value="9:16">9:16 (Vertical — TikTok/Reels)</option>
                <option value="16:9">16:9 (Horizontal)</option>
                <option value="1:1">1:1 (Square)</option>
                <option value="3:4">3:4</option>
                <option value="4:5">4:5</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Language</label>
              <select className="form-select" value={targetLanguage} onChange={(e) => setTargetLanguage(e.target.value)}>
                <option value="english">English (Global)</option>
                <option value="hinglish">Hinglish (Hindi in Roman script)</option>
                <option value="hindi">Hindi</option>
                <option value="indonesian">Indonesian (Bahasa Indonesia)</option>
                <option value="spanish">Spanish</option>
                <option value="auto">Auto Detect</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Font Style</label>
              <select className="form-select" value={fontStyle} onChange={(e) => setFontStyle(e.target.value)}>
                <option value="MUKTA">Mukta (Hindi / Hinglish / Global)</option>
                <option value="HORMOZI">Hormozi (Bold)</option>
                <option value="DEFAULT">Default (Montserrat)</option>
                <option value="STORYTELLER">Storyteller (Inter)</option>
                <option value="CINEMATIC">Cinematic (Bebas Neue)</option>
              </select>
            </div>

            {/* Clip Duration Strategy */}
            <div style={{ marginTop: '16px', paddingTop: '14px', borderTop: '1px solid var(--border-color)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <label className="form-label" style={{ marginBottom: 0 }}>⏱️ Clip Duration & Virality</label>
                <span style={{ fontSize: '11px', color: 'var(--accent)', fontWeight: 600, background: 'var(--accent-dim)', padding: '2px 8px', borderRadius: 'var(--radius-sm)' }}>
                  {minClipDuration}s – {maxClipDuration}s
                </span>
              </div>

              {/* Quick Presets */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px', marginBottom: '10px' }}>
                <button
                  type="button"
                  className={`btn btn-xs ${minClipDuration === 20 && maxClipDuration === 60 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(20); setMaxClipDuration(60) }}
                  style={{ fontSize: '11px', padding: '6px 8px', textAlign: 'left' }}
                >
                  ⚡ Viral Shorts (20–60s)
                </button>
                <button
                  type="button"
                  className={`btn btn-xs ${minClipDuration === 30 && maxClipDuration === 90 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(30); setMaxClipDuration(90) }}
                  style={{ fontSize: '11px', padding: '6px 8px', textAlign: 'left' }}
                >
                  📈 Balanced Story (30–90s)
                </button>
                <button
                  type="button"
                  className={`btn btn-xs ${minClipDuration === 15 && maxClipDuration === 45 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(15); setMaxClipDuration(45) }}
                  style={{ fontSize: '11px', padding: '6px 8px', textAlign: 'left' }}
                >
                  🔥 Snappy Hook (15–45s)
                </button>
                <button
                  type="button"
                  className={`btn btn-xs ${minClipDuration === 60 && maxClipDuration === 180 ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => { setMinClipDuration(60); setMaxClipDuration(180) }}
                  style={{ fontSize: '11px', padding: '6px 8px', textAlign: 'left' }}
                >
                  🎙️ Deep Dive (60–180s)
                </button>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div>
                  <label style={{ fontSize: '11px', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Min Duration (sec)</label>
                  <input
                    className="form-input"
                    type="number"
                    min="10"
                    max="300"
                    value={minClipDuration}
                    onChange={(e) => setMinClipDuration(parseInt(e.target.value) || 10)}
                    style={{ padding: '6px 10px', fontSize: '12px' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '11px', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Max Duration (sec)</label>
                  <input
                    className="form-input"
                    type="number"
                    min="15"
                    max="600"
                    value={maxClipDuration}
                    onChange={(e) => setMaxClipDuration(parseInt(e.target.value) || 30)}
                    style={{ padding: '6px 10px', fontSize: '12px' }}
                  />
                </div>
              </div>

              {minClipDuration >= maxClipDuration && (
                <p style={{ color: 'var(--warning)', fontSize: '11px', marginTop: '6px' }}>
                  ⚠️ Min duration must be less than Max duration.
                </p>
              )}

              <p className="form-hint" style={{ marginTop: '6px', fontSize: '11px' }}>
                💡 Clips between 20–60 seconds achieve higher completion rates to boost virality on TikTok & Shorts.
              </p>
            </div>
          </div>

          {/* AI Settings */}
          <div className="config-section">
            <h4>🤖 AI & Whisper</h4>
            <div className="form-group">
              <label className="form-label">AI Provider</label>
              <select
                className="form-select"
                value={aiProvider}
                onChange={(e) => {
                  const newProvider = e.target.value
                  setAiProvider(newProvider)
                  if (PROVIDER_MODELS[newProvider]?.[0]) {
                    setAiModel(PROVIDER_MODELS[newProvider][0].id)
                  }
                }}
              >
                <option value="sambanova">SambaNova Cloud (Ultra Fast)</option>
                <option value="gemini">Google Gemini</option>
                <option value="nvidia">NVIDIA NIM</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">AI Model</label>
              <select className="form-select" value={aiModel} onChange={(e) => setAiModel(e.target.value)}>
                {(PROVIDER_MODELS[aiProvider] || []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Whisper Model</label>
              <select className="form-select" value={whisperModel} onChange={(e) => setWhisperModel(e.target.value)}>
                <option value="large-v3-turbo">large-v3-turbo (Recommended - Fast & Accurate)</option>
                <option value="large-v3">large-v3 (Best Quality)</option>
                <option value="medium">medium (Balanced)</option>
                <option value="small">small (Fast)</option>
                <option value="base">base (Fastest)</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Device</label>
              <select className="form-select" value={whisperDevice} onChange={(e) => setWhisperDevice(e.target.value)}>
                <option value="cpu">CPU (Recommended for Mac)</option>
                <option value="cuda">CUDA (NVIDIA GPU)</option>
                <option value="auto">Auto</option>
              </select>
            </div>
          </div>

          {/* Feature Toggles */}
          <div className="config-section">
            <h4>✨ Features & Modes</h4>
            <ToggleRow label="Split-Screen" desc="Podcast 2-speaker top/bottom split" checked={useSplitScreen} onChange={setUseSplitScreen} />
            {useSplitScreen && (
              <div style={{ paddingLeft: '24px', borderLeft: '2px solid var(--accent)', marginBottom: '10px' }}>
                <ToggleRow label="Dynamic Split (Choppity-style)" desc="Auto switch full-screen (1 speaker) and split (2 speakers)" checked={useDynamicSplit} onChange={setUseDynamicSplit} />
                <ToggleRow label="Smart Auto-Zoom" desc="Automatically zooms into speaker face to remove background distraction" checked={splitAutoZoom} onChange={setSplitAutoZoom} />
              </div>
            )}
            <ToggleRow label="Camera-Switch" desc="Auto switch camera to active speaker" checked={useCameraSwitch} onChange={setUseCameraSwitch} />
            <ToggleRow label="B-Roll Footage" desc="Insert stock footage" checked={useBroll} onChange={setUseBroll} />
            <ToggleRow label="Hook Glitch" desc="Glitch transition intro" checked={useHookGlitch} onChange={setUseHookGlitch} />
            <ToggleRow label="Background Music" desc="Auto BGM matching" checked={useBgm} onChange={setUseBgm} />
            <ToggleRow label="Karaoke Effect" desc="Word-by-word highlight" checked={useKaraoke} onChange={setUseKaraoke} />
            <ToggleRow label="Text Behind Person (3D Depth)" desc="Sandwich kinetic text/subtitles behind the speaker using AI segmentation" checked={textBehindPerson} onChange={setTextBehindPerson} />
            <ToggleRow label="Hook V2" desc="Multi-hook intro clips" checked={hookV2} onChange={setHookV2} />
            <ToggleRow label="Silence Trim" desc="Remove dead air" checked={silenceTrim} onChange={setSilenceTrim} />
            <ToggleRow label="YouTube Subs" desc="Skip Whisper if available" checked={useDlpSubs} onChange={setUseDlpSubs} />
            <ToggleRow label="No Subtitles" desc="Render without text" checked={noSubs} onChange={setNoSubs} />
            <ToggleRow label="Bypass AI" desc="Reuse gemini JSON (if exist)" checked={loadGeminiJson} onChange={setLoadGeminiJson} />
          </div>
        </div>

        {/* Error */}
        {error && (
          <div style={{ background: 'var(--error-dim)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-md)', padding: '12px 16px', marginBottom: '16px', color: 'var(--error)', fontSize: '13px' }}>
            ⚠️ {error}
          </div>
        )}

        {/* Submit */}
        <button type="submit" className="btn btn-primary" disabled={submitting} style={{ fontSize: '14px', padding: '12px 28px' }}>
          {submitting ? <><span className="spinner"></span> Processing...</> : '🚀 Start Clipping'}
        </button>
      </form>
    </div>
  )
}

function ToggleRow({ label, desc, checked, onChange }) {
  return (
    <div className="toggle-row">
      <div>
        <div className="toggle-label">{label}</div>
        {desc && <div className="toggle-desc">{desc}</div>}
      </div>
      <label className="toggle-switch">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span className="toggle-slider"></span>
      </label>
    </div>
  )
}

export default NewJob
