// =============================================================================
// Arveum Frontend (Thin Client) — talks to Python backend via WebSocket
// =============================================================================
// Browser ist nur Mic, Speaker und UI. Alle Voice-Logik, Tool-Execution und
// Realtime-API-Bridge laufen im Python-Backend (siehe ../backend/).

// --- Config: nur UI-Wahlen, keine API-Keys mehr ---
const CONFIG = {
    openaiVoice: 'shimmer',
    realtimeModel: 'gpt-realtime',
    backendLlmModel: 'claude-haiku-4-5',
    questionCount: 8,
};

// --- Lokaler State (nur UI-Mirror — Backend ist autoritativ) ---
const STATE = {
    callActive: false,
    muted: false,
    mode: 'idle',
    callerEmail: null,
    selectedJobId: null,
    selectedJobTitle: null,
    selectedJobLocation: null,
    cvUploaded: false,
    score: null,
    highlights: [],
    currentQuestionIdx: 0,
    totalQuestions: 0,
};

let ws = null;
let player = null;
let micStream = null;
let audioCtx = null;
let workletNode = null;

const $ = id => document.getElementById(id);

// =============================================================================
// SETUP
// =============================================================================
window.addEventListener('DOMContentLoaded', async () => {
    loadConfigFromStorage();
    bindUI();
    await loadAndPopulateContext();
    logEvent('sys', 'App geladen. Stelle sicher dass das Backend läuft (uvicorn main:app), dann Anruf starten.');
});

async function loadAndPopulateContext() {
    try {
        const company = await (await fetch('/api/data/company.json')).json();
        const jobs = (await (await fetch('/api/data/jobs.json')).json()).jobs;
        const benefits = await (await fetch('/api/data/benefits.json')).json();
        const locations = (await (await fetch('/api/data/locations.json')).json()).locations;
        $('contextCompany').textContent =
            `${company.name} — ${company.tagline}\n` +
            `Größe: ${company.size}\n` +
            `Mission: ${company.mission}\n` +
            `Werte:\n  - ${company.values.join('\n  - ')}\n` +
            `Kultur: ${company.team_dynamics}\n${company.communication_culture}\n` +
            `Differenzierung: ${company.differentiator}\n` +
            `Was wir nicht machen: ${company.what_we_dont_do}`;
        $('contextJobs').textContent = JSON.stringify(jobs, null, 2);
        $('contextBenefits').textContent = JSON.stringify(benefits, null, 2);
        $('contextLocations').textContent = JSON.stringify(locations, null, 2);
    } catch (e) {
        logEvent('err', 'Mock-Daten konnten nicht vom Backend geladen werden — läuft das Backend auf Port 8000?');
    }
}

function loadConfigFromStorage() {
    const saved = localStorage.getItem('arveum-config-v2');
    if (!saved) return;
    try {
        const c = JSON.parse(saved);
        Object.assign(CONFIG, c);
        $('openaiVoice').value = c.openaiVoice || 'shimmer';
        $('modelSelect').value = c.backendLlmModel || 'claude-haiku-4-5';
        $('questionCount').value = String(c.questionCount || 8);
        $('realtimeModel').value = c.realtimeModel || 'gpt-realtime';
    } catch (e) { console.error('config parse failed', e); }
}

function saveConfig() {
    CONFIG.openaiVoice = $('openaiVoice').value;
    CONFIG.backendLlmModel = $('modelSelect').value;
    CONFIG.questionCount = parseInt($('questionCount').value, 10);
    CONFIG.realtimeModel = $('realtimeModel').value;
    localStorage.setItem('arveum-config-v2', JSON.stringify(CONFIG));
    setStatus('Konfig gespeichert', 'active');
    logEvent('sys', 'Konfiguration gespeichert.');
    setTimeout(() => setStatus('Bereit'), 1500);
}

function bindUI() {
    $('saveConfig').addEventListener('click', saveConfig);
    $('callBtn').addEventListener('click', startCall);
    $('endBtn').addEventListener('click', endCall);
    $('muteBtn').addEventListener('click', toggleMute);
    $('emailClose').addEventListener('click', () => $('emailModal').classList.add('hidden'));
    $('uploadBtn').addEventListener('click', () => $('cvFileInput').click());
    $('cvFileInput').addEventListener('change', e => handleCvFile(e.target.files[0]));
    $('logClear').addEventListener('click', () => { $('logList').innerHTML = ''; });
}

// =============================================================================
// PCM-Recorder Worklet (inline via Blob-URL — keine separate Datei)
// =============================================================================
const PCM_RECORDER_WORKLET = `
class PCMRecorderProcessor extends AudioWorkletProcessor {
    process(inputs) {
        const input = inputs[0];
        if (!input || input.length === 0) return true;
        const float32 = input[0];
        if (!float32 || float32.length === 0) return true;
        const pcm16 = new Int16Array(float32.length);
        for (let i = 0; i < float32.length; i++) {
            const s = Math.max(-1, Math.min(1, float32[i]));
            pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
        return true;
    }
}
registerProcessor('pcm-recorder', PCMRecorderProcessor);
`;

async function loadPCMRecorderWorklet(ctx) {
    const blob = new Blob([PCM_RECORDER_WORKLET], { type: 'application/javascript' });
    const url = URL.createObjectURL(blob);
    await ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
}

// =============================================================================
// AudioPlayer — queued PCM16-Wiedergabe + Drain-Detection
// =============================================================================
class AudioPlayer {
    constructor(sampleRate = 24000) {
        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate });
        this.sampleRate = sampleRate;
        this.nextStartTime = 0;
        this.activeSources = [];
        this.expectingMore = false;     // true = Backend sendet noch Chunks; false = darf nach Drain melden
        this.onDrain = null;
    }

    play(pcm16Buffer) {
        const int16 = new Int16Array(pcm16Buffer);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
        const ab = this.audioCtx.createBuffer(1, float32.length, this.sampleRate);
        ab.copyToChannel(float32, 0);
        const src = this.audioCtx.createBufferSource();
        src.buffer = ab;
        src.connect(this.audioCtx.destination);
        const now = this.audioCtx.currentTime;
        const startAt = Math.max(this.nextStartTime, now);
        src.start(startAt);
        this.nextStartTime = startAt + ab.duration;
        this.activeSources.push(src);
        src.onended = () => {
            const idx = this.activeSources.indexOf(src);
            if (idx > -1) this.activeSources.splice(idx, 1);
            this._maybeNotifyDrain();
        };
    }

    markEndExpected() {
        this.expectingMore = false;
        // Falls die Queue bereits leer ist → sofort Drain melden
        if (!this.isPlaying()) this._maybeNotifyDrain();
    }

    expectMore() { this.expectingMore = true; }

    _maybeNotifyDrain() {
        if (this.expectingMore) return;
        if (this.activeSources.length > 0) return;
        if (this.nextStartTime > this.audioCtx.currentTime + 0.05) return;
        if (this.onDrain) this.onDrain();
    }

    isPlaying() { return this.activeSources.length > 0; }

    stop() {
        for (const s of this.activeSources) {
            try { s.stop(); } catch (e) {}
        }
        this.activeSources = [];
        this.nextStartTime = this.audioCtx.currentTime;
    }

    async close() {
        this.stop();
        try { await this.audioCtx.close(); } catch (e) {}
    }
}

// =============================================================================
// Helpers
// =============================================================================
function arrayBufferToBase64(buf) {
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
}

function base64ToArrayBuffer(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
}

function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(obj));
    }
}

// =============================================================================
// Call Control
// =============================================================================
async function startCall() {
    setStatus('Verbinde mit Backend...', 'active');
    setMicState('🔌 Verbinde...');

    const wsUrl = `ws${location.protocol === 'https:' ? 's' : ''}://${location.host}/ws/voice`;
    try {
        ws = new WebSocket(wsUrl);
        await new Promise((resolve, reject) => {
            ws.onopen = resolve;
            ws.onerror = () => reject(new Error('WebSocket-Fehler — läuft das Backend auf Port 8000?'));
        });
    } catch (e) {
        logEvent('err', 'Backend-Verbindung: ' + e.message);
        setStatus('Backend nicht erreichbar', 'error');
        setMicState('⚪ Nicht aktiv');
        return;
    }

    ws.onmessage = handleBackendMessage;
    ws.onclose = () => {
        if (STATE.callActive) {
            logEvent('err', 'Backend-Verbindung getrennt');
            cleanupCall();
        }
    };

    try {
        await setupAudio();
    } catch (e) {
        logEvent('err', 'Mikrofon-Setup: ' + e.message);
        alert('Mikrofon-Zugriff fehlgeschlagen: ' + e.message);
        if (ws) ws.close();
        return;
    }

    STATE.callActive = true;
    $('callBtn').disabled = true;
    $('endBtn').disabled = false;
    $('muteBtn').disabled = false;
    setStatus('Call aktiv', 'active');

    wsSend({
        type: 'start_call',
        config: {
            openaiVoice: CONFIG.openaiVoice,
            realtimeModel: CONFIG.realtimeModel,
            backendLlmModel: CONFIG.backendLlmModel,
            questionCount: CONFIG.questionCount,
        },
    });
}

async function setupAudio() {
    player = new AudioPlayer(24000);
    player.expectMore();   // ist Default — wenn Backend agent_audio_end sendet, wird auf false gesetzt
    player.onDrain = () => wsSend({ type: 'playback_drained' });

    micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    await loadPCMRecorderWorklet(audioCtx);
    const source = audioCtx.createMediaStreamSource(micStream);
    workletNode = new AudioWorkletNode(audioCtx, 'pcm-recorder');
    workletNode.port.onmessage = e => {
        if (!STATE.muted) {
            wsSend({ type: 'audio_chunk', data: arrayBufferToBase64(e.data) });
        }
    };
    source.connect(workletNode);
    logEvent('sys', 'Mic-Capture aktiv (24kHz PCM16 streaming → Backend)');
}

async function endCall() {
    wsSend({ type: 'end_call' });
    cleanupCall();
}

function cleanupCall() {
    if (workletNode) { try { workletNode.disconnect(); } catch (e) {} }
    if (micStream) { try { micStream.getTracks().forEach(t => t.stop()); } catch (e) {} }
    if (audioCtx && audioCtx.state !== 'closed') { try { audioCtx.close(); } catch (e) {} }
    if (player) player.close();
    if (ws && ws.readyState === WebSocket.OPEN) ws.close();
    workletNode = null; micStream = null; audioCtx = null; player = null; ws = null;

    STATE.callActive = false;
    $('callBtn').disabled = false;
    $('endBtn').disabled = true;
    $('muteBtn').disabled = true;
    setMicState('⚪ Nicht aktiv');
    setStatus('Bereit');
}

function toggleMute() {
    STATE.muted = !STATE.muted;
    $('muteBtn').textContent = STATE.muted ? '🔊 Stumm aufheben' : '🔇 Stummschalten';
    setMicState(STATE.muted ? '🔇 Stummgeschaltet' : '🎙️ Höre zu...');
    wsSend({ type: 'mute', muted: STATE.muted });
}

// =============================================================================
// Backend → Browser Event-Handler
// =============================================================================
function handleBackendMessage(event) {
    let msg;
    try { msg = JSON.parse(event.data); } catch (e) { return; }

    switch (msg.type) {
        case 'agent_audio':
            if (player) {
                player.expectMore();
                player.play(base64ToArrayBuffer(msg.data));
            }
            break;
        case 'agent_audio_end':
            if (player) player.markEndExpected();
            break;
        case 'stop_playback':
            if (player) player.stop();
            break;
        case 'transcript_user': appendMessage('user', msg.text); break;
        case 'transcript_agent': appendMessage('agent', msg.text); break;
        case 'system_message': appendMessage('system', msg.text); break;
        case 'tool_called':
            appendMessage('tool', `🔧 ${msg.name}(${JSON.stringify(msg.input)})`);
            break;
        case 'log': logEvent(msg.logtype, msg.message, msg.data); break;
        case 'mic_state': setMicState(msg.text); break;
        case 'status': setStatus(msg.text, msg.className || ''); break;
        case 'state_update':
            Object.assign(STATE, msg.state || {});
            updateDashboard();
            break;
        case 'show_email_modal': showEmailModal(msg.email, msg.time); break;
        case 'call_ended': cleanupCall(); break;
        case 'error':
            logEvent('err', msg.message);
            setStatus(msg.message, 'error');
            break;
    }
}

// =============================================================================
// CV-Upload (über WebSocket als base64)
// =============================================================================
async function handleCvFile(file) {
    if (!file) return;
    if (file.type !== 'application/pdf') {
        alert('Bitte PDF-Datei wählen.');
        return;
    }
    $('emailModal').classList.add('hidden');
    const reader = new FileReader();
    reader.onload = () => {
        const base64 = reader.result.split(',')[1];
        wsSend({ type: 'cv_uploaded', filename: file.name, data: base64 });
    };
    reader.readAsDataURL(file);
}

// =============================================================================
// UI
// =============================================================================
function setStatus(text, className = '') {
    const el = $('status');
    el.textContent = text;
    el.className = 'status' + (className ? ' ' + className : '');
}

function setMicState(text) { $('micState').textContent = text; }

function appendMessage(role, content) {
    const transcript = $('transcript');
    const hint = transcript.querySelector('.hint');
    if (hint) hint.remove();
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.textContent = content;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
}

function updateDashboard() {
    $('dashStatus').textContent = labelForMode(STATE.mode);
    $('dashEmail').textContent = STATE.callerEmail || '—';
    if (STATE.selectedJobTitle) {
        $('dashRole').textContent = `${STATE.selectedJobTitle} (${STATE.selectedJobLocation || ''})`;
    } else {
        $('dashRole').textContent = STATE.selectedJobId || '—';
    }
    $('dashCV').textContent = STATE.cvUploaded ? '✅ hochgeladen' : '—';
    $('dashScore').textContent = STATE.score != null ? `${STATE.score}/100` : '—';
    const ul = $('dashHighlights');
    ul.innerHTML = '';
    (STATE.highlights || []).forEach(h => {
        const li = document.createElement('li'); li.textContent = h; ul.appendChild(li);
    });
}

function labelForMode(m) {
    return ({
        idle: 'Kein Call aktiv',
        free: 'Free Mode (offene Konversation)',
        awaiting_upload: 'Warte auf CV-Upload',
        cv_received: 'CV empfangen, generiere Fragen',
        interview: 'Interview läuft',
        wrapping: 'Abschluss',
        ended: 'Call beendet',
    })[m] || m;
}

function showEmailModal(email, time) {
    $('emailTo').textContent = email;
    $('emailTime').textContent = time || new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    $('emailModal').classList.remove('hidden');
}

// =============================================================================
// Logging (Backend pusht alle Events via WebSocket — UI zeigt sie nur an)
// =============================================================================
function logEvent(type, message, data) {
    const list = $('logList');
    if (!list) return;
    const div = document.createElement('div');
    div.className = `log-entry t-${type}`;
    const now = new Date();
    const time = now.toLocaleTimeString('de-DE', { hour12: false }) + '.' + String(now.getMilliseconds()).padStart(3, '0');
    const labels = { stt: 'STT', llm: 'LLM', tool: 'TOOL', tts: 'TTS', vad: 'VAD', sys: 'SYS', err: 'ERR' };
    let html = `<span class="time">[${time}]</span><span class="label">${labels[type] || type}:</span> ${escapeHtml(message)}`;
    if (data !== undefined && data !== null) {
        const dataStr = typeof data === 'string' ? data : JSON.stringify(data);
        html += ` <span class="data">${escapeHtml(dataStr)}</span>`;
    }
    div.innerHTML = html;
    list.appendChild(div);
    list.scrollTop = list.scrollHeight;
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}
