import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, AirVent, BellRing, BrainCircuit, Cat, ChevronRight, CloudSun, DoorOpen,
  Flame, Gauge, Lightbulb, Mic, MicOff, Radio, ShieldCheck, Sparkles, Thermometer,
  Volume2, Wind
} from "lucide-react";
import { apiGet, apiPost, apiPostBlob, apiPostForm } from "./api/client";
import "./styles/app.css";

type UserProfile = { username: string; display_name: string; role: string };
type Room = { key: string; name: string; floor: string; has_voice_point: boolean };
type Pet = { key: string; name: string; species: string; home_state: string; last_known_room?: string | null };
type ActivityItem = { id: number; event_type: string; summary: string; actor?: string; level: number; created_at: string };
type Usage = { daily_spend: number; monthly_spend: number; daily_limit: number; monthly_limit: number; enabled: boolean };
type VoiceStatus = { transcription_available: boolean; tts_available: boolean; max_seconds: number; transcription_model: string };
type Status = {
  status: string;
  home_assistant: { enabled: boolean; reachable: boolean };
  database: { rooms: number };
  voice?: VoiceStatus;
};
type AssistantResult = {
  conversation_id: string;
  response: string;
  used_remote_llm: boolean;
  estimated_cost: number;
};
type VoiceTurnResult = AssistantResult & {
  transcript: string;
  transcription_model: string;
  transcription_estimated_cost: number;
};
type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: any) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  }
}

const roomPositions: Record<string, { x: number; y: number; w: number; h: number }> = {
  entrada: { x: 6, y: 37, w: 23, h: 24 },
  cocina_salon: { x: 31, y: 8, w: 63, h: 35 },
  salon_entresuelo: { x: 31, y: 46, w: 32, h: 22 },
  bano: { x: 66, y: 46, w: 28, h: 22 },
  vestidor: { x: 6, y: 64, w: 23, h: 27 },
  dormitorio_matrimonio: { x: 31, y: 71, w: 37, h: 20 },
  habitacion_bebe: { x: 70, y: 71, w: 24, h: 20 }
};

function App() {
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [pets, setPets] = useState<Pet[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [input, setInput] = useState("ALI, enciende la cocina");
  const [reply, setReply] = useState("");
  const [selectedRoom, setSelectedRoom] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isListening, setIsListening] = useState(false);
  const [isVoiceProcessing, setIsVoiceProcessing] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState("Pulsa y mantén para hablar con ALI");
  const [latency, setLatency] = useState<number | null>(null);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const recordingStream = useRef<MediaStream | null>(null);

  async function refresh() {
    const [nextStatus, nextUsers, nextRooms, nextPets, nextActivity, nextUsage] = await Promise.all([
      apiGet<Status>("/api/status"), apiGet<UserProfile[]>("/api/users"), apiGet<Room[]>("/api/rooms"),
      apiGet<Pet[]>("/api/pets"), apiGet<ActivityItem[]>("/api/activity"), apiGet<Usage>("/api/usage/openai")
    ]);
    setStatus(nextStatus);
    setUsers(nextUsers);
    setRooms(nextRooms);
    setPets(nextPets);
    setActivity(nextActivity);
    setUsage(nextUsage);
  }

  useEffect(() => { refresh().catch(console.error); }, []);
  const selected = rooms.find((room) => room.key === selectedRoom);
  const voiceRooms = useMemo(() => rooms.filter((room) => room.has_voice_point), [rooms]);
  const apiTranscriptionAvailable = Boolean(status?.voice?.transcription_available);
  const apiTtsAvailable = Boolean(status?.voice?.tts_available);

  function speakWithBrowser(text: string) {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "es-ES";
    utterance.rate = 1.06;
    window.speechSynthesis.speak(utterance);
  }

  async function speakReply(text: string) {
    if (apiTtsAvailable) {
      try {
        const blob = await apiPostBlob("/api/voice/speech", { text });
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        audio.addEventListener("ended", () => URL.revokeObjectURL(audioUrl), { once: true });
        await audio.play();
        return;
      } catch (error) {
        console.warn("OpenAI TTS unavailable; using browser voice", error);
      }
    }
    speakWithBrowser(text);
  }

  function showReply(result: AssistantResult, elapsed: number, source: "texto" | "voz") {
    setConversationId(result.conversation_id);
    setLatency(elapsed);
    setReply(result.response);
    setVoiceNotice(`ALI respondió por ${source} en ${elapsed} ms · ${result.used_remote_llm ? "modelo remoto" : "modo local"}`);
    void speakReply(result.response);
    refresh().catch(console.error);
  }

  async function askAli(text = input) {
    if (!text.trim()) return;
    const start = performance.now();
    try {
      const result = await apiPost<AssistantResult>("/api/ask", {
        text,
        conversation_id: conversationId,
        probable_user: "ismael",
        room_key: selectedRoom || "cocina_salon"
      });
      showReply(result, Math.round(performance.now() - start), "texto");
    } catch (error) {
      console.error(error);
      setVoiceNotice("ALI no ha podido procesar la frase. Comprueba que el sistema está operativo.");
    }
  }

  function startBrowserVoice() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setVoiceNotice("Este navegador no ofrece reconocimiento de voz. Activa la API de voz o prueba Chrome/Safari.");
      return;
    }
    const instance = new Recognition();
    recognition.current = instance;
    instance.lang = "es-ES";
    instance.interimResults = false;
    instance.continuous = false;
    instance.onresult = (event) => {
      const text = event.results[0][0].transcript;
      setInput(text);
      setVoiceNotice(`Reconocido: “${text}”`);
      void askAli(text);
    };
    instance.onerror = () => setVoiceNotice("No he podido oírte. Revisa el permiso de micrófono.");
    instance.onend = () => setIsListening(false);
    try {
      instance.start();
      setIsListening(true);
      setVoiceNotice("Escuchando con el reconocimiento del navegador…");
    } catch (error) {
      console.error(error);
      setVoiceNotice("El micrófono ya está en uso o no tiene permiso.");
    }
  }

  async function sendVoiceRecording(audio: Blob) {
    setIsVoiceProcessing(true);
    setVoiceNotice("Transcribiendo de forma segura…");
    const form = new FormData();
    form.append("file", audio, "ali-voice.webm");
    if (conversationId) form.append("conversation_id", conversationId);
    form.append("probable_user", "ismael");
    form.append("room_key", selectedRoom || "cocina_salon");
    const start = performance.now();
    try {
      const result = await apiPostForm<VoiceTurnResult>("/api/voice/turn", form);
      setInput(result.transcript);
      showReply(result, Math.round(performance.now() - start), "voz");
    } catch (error) {
      console.error(error);
      setVoiceNotice("No he podido transcribir esta frase. Prueba de nuevo o usa el modo de navegador.");
    } finally {
      setIsVoiceProcessing(false);
      setIsListening(false);
    }
  }

  async function startApiVoice() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      startBrowserVoice();
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    });
    recordingStream.current = stream;
    const preferredMimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
      .find((mimeType) => MediaRecorder.isTypeSupported(mimeType));
    const instance = preferredMimeType ? new MediaRecorder(stream, { mimeType: preferredMimeType }) : new MediaRecorder(stream);
    const chunks: Blob[] = [];
    const responseMimeType = instance.mimeType || preferredMimeType || "audio/webm";
    recorder.current = instance;
    instance.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    instance.onerror = () => setVoiceNotice("Se ha interrumpido la grabación. Prueba otra vez.");
    instance.onstop = () => {
      recorder.current = null;
      recordingStream.current?.getTracks().forEach((track) => track.stop());
      recordingStream.current = null;
      const audio = new Blob(chunks, { type: responseMimeType });
      if (!audio.size) {
        setIsListening(false);
        setVoiceNotice("No he recibido audio. Revisa el permiso de micrófono.");
        return;
      }
      void sendVoiceRecording(audio);
    };
    instance.start();
    setIsListening(true);
    setVoiceNotice(`Escuchando con OpenAI · máximo ${status?.voice?.max_seconds || 20} segundos`);
  }

  function startVoice() {
    if (isListening || isVoiceProcessing) return;
    if (apiTranscriptionAvailable) {
      startApiVoice().catch((error) => {
        console.error(error);
        setVoiceNotice("No he podido abrir el micrófono para la API. Probando el reconocimiento del navegador…");
        startBrowserVoice();
      });
      return;
    }
    startBrowserVoice();
  }

  function stopVoice() {
    if (recorder.current && recorder.current.state !== "inactive") {
      recorder.current.stop();
      return;
    }
    recognition.current?.stop();
  }

  function commandFor(room: Room, action: string) {
    const text = `ALI, ${action} ${room.name.toLowerCase()}`;
    setInput(text);
    void askAli(text);
  }

  return <main className="ali-shell">
    <div className="scanlines" />
    <header className="hud-header">
      <div className="brand"><span className="brand-orb"><Sparkles size={22} /></span><div><p>ALI HOME / CORE v0.2</p><h1>ALI <em>HOME</em></h1></div></div>
      <div className="header-status"><span className={status?.status === "ok" ? "pulse-dot online" : "pulse-dot"} /> SISTEMA {status?.status === "ok" ? "OPERATIVO" : "CONECTANDO"}<small>LOCAL-FIRST · {apiTranscriptionAvailable ? "VOZ API PRIVADA" : "VOZ DEL NAVEGADOR"}</small></div>
    </header>

    <section className="command-deck panel-glow">
      <div className="voice-core">
        <div className={`voice-ring ${isListening || isVoiceProcessing ? "listening" : ""}`}><Mic size={34} /></div>
        <div><span className="eyebrow">INTERFAZ DE VOZ · {apiTranscriptionAvailable ? "OPENAI SEGURO" : "NAVEGADOR LOCAL"}</span><h2>{isVoiceProcessing ? "PROCESANDO" : isListening ? "TE ESCUCHO" : "HABLA CON ALI"}</h2><p>{voiceNotice}</p></div>
        <button
          className="talk-button"
          disabled={isVoiceProcessing}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            startVoice();
          }}
          onPointerUp={stopVoice}
          onPointerCancel={stopVoice}
          onKeyDown={(event) => {
            if ((event.key === " " || event.key === "Enter") && !event.repeat) {
              event.preventDefault();
              startVoice();
            }
          }}
          onKeyUp={(event) => {
            if (event.key === " " || event.key === "Enter") {
              event.preventDefault();
              stopVoice();
            }
          }}
          aria-label="Mantén pulsado para hablar con ALI"
          aria-pressed={isListening}
        >
          {isListening ? <MicOff size={19} /> : <Mic size={19} />} {isVoiceProcessing ? "PROCESANDO…" : isListening ? "SOLTAR PARA ENVIAR" : "MANTÉN PARA HABLAR"}
        </button>
      </div>
      <div className="text-command"><input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void askAli()} /><button onClick={() => void askAli()}>ENVIAR <ChevronRight size={17} /></button></div>
      {reply && <div className="ali-reply"><Volume2 size={18} /><div><span>ALI</span>{reply}</div>{latency !== null && <b>{latency} ms</b>}</div>}
    </section>

    <section className="overview-grid">
      <article className="telemetry panel-glow"><span className="eyebrow">ESTADO AMBIENTAL</span><div className="temp-value"><Thermometer /> <strong>—<sup>°C</sup></strong></div><p>Sin sensor térmico conectado</p><div className="telemetry-row"><Wind size={16} /> Aire acondicionado <b>Sin integrar</b></div><div className="telemetry-row"><CloudSun size={16} /> Clima exterior <b>Pendiente</b></div></article>
      <article className="telemetry panel-glow"><span className="eyebrow">SEGURIDAD PERIMETRAL</span><div className="security-number"><ShieldCheck size={30} /><strong>—</strong></div><p>Puertas y ventanas sin sensores</p><div className="telemetry-row"><DoorOpen size={16} /> Puertas <b>Sin datos</b></div><div className="telemetry-row"><BellRing size={16} /> Alertas <b>0</b></div></article>
      <article className="telemetry panel-glow"><span className="eyebrow">INTELIGENCIA ALI</span><div className="security-number"><BrainCircuit size={30} /><strong>LOCAL</strong></div><p>{users.map((user) => user.display_name).join(" · ") || "Perfiles cargando"}</p><div className="telemetry-row"><Radio size={16} /> Voz <b>{apiTranscriptionAvailable ? "API privada" : voiceRooms.length ? "Punto previsto" : "Prueba web"}</b></div><div className="telemetry-row"><Gauge size={16} /> GPT <b>{usage?.enabled ? "Activo" : "Apagado"}</b></div></article>
    </section>

    <section className="home-grid">
      <article className="house-panel panel-glow"><div className="section-heading"><div><span className="eyebrow">VISTA SATÉLITE · PLANO ESQUEMÁTICO</span><h2>CASA <em>EN VIVO</em></h2></div><span className="house-live"><span className="pulse-dot online" /> {status?.home_assistant?.reachable ? "SENSORES EN LÍNEA" : "SIN SENSORES CONECTADOS"}</span></div>
        <div className="house-map">{rooms.map((room) => { const pos = roomPositions[room.key] || { x: 8, y: 8, w: 25, h: 20 }; return <button key={room.key} className={`map-room ${selectedRoom === room.key ? "selected" : ""}`} style={{ left: `${pos.x}%`, top: `${pos.y}%`, width: `${pos.w}%`, height: `${pos.h}%` }} onClick={() => setSelectedRoom(room.key)}><span>{room.name}</span><small>{room.has_voice_point ? "◉ VOZ" : "○ SIN VOZ"}</small></button>; })}<div className="map-radar" /></div>
        <div className="map-legend"><span><Lightbulb size={14} /> Iluminación: pendiente</span><span><AirVent size={14} /> Clima: pendiente</span><span><Mic size={14} /> Micrófono: {apiTranscriptionAvailable ? "API segura" : "prueba web"}</span></div>
      </article>

      <aside className="room-console panel-glow"><span className="eyebrow">CONSOLA DE ESTANCIA</span>{selected ? <><h2>{selected.name}</h2><p>{selected.floor} · {selected.has_voice_point ? "Punto de voz previsto" : "Sin punto de voz"}</p><div className="control-state"><Lightbulb /> Iluminación <b>Sin conectar</b></div><div className="control-state"><AirVent /> Aire acondicionado <b>Sin conectar</b></div><div className="control-state"><DoorOpen /> Puertas / ventanas <b>Sin sensor</b></div><div className="action-buttons"><button onClick={() => commandFor(selected, "enciende")}>ENCENDER</button><button onClick={() => commandFor(selected, "apaga")}>APAGAR</button></div></> : <div className="select-room"><HomeGlyph /><p>Selecciona una estancia en el plano para ver sus controles.</p></div>}<div className="pet-card"><Cat size={18} /><div><span>{pets[0]?.name || "CAT"}</span><b>{pets[0]?.home_state || "Sin datos"}</b></div></div></aside>
    </section>

    <section className="bottom-grid"><article className="activity-panel panel-glow"><div className="section-heading"><div><span className="eyebrow">EVENTOS RECIENTES</span><h2>ACTIVITY LOG</h2></div><Activity size={20} /></div>{activity.slice(0, 4).map((item) => <div className="activity-row" key={item.id}><span className="pulse-dot online" /><div><b>{item.event_type}</b><p>{item.summary}</p></div><time>{new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></div>)}{!activity.length && <p className="muted">Esperando actividad de ALI…</p>}</article><article className="safety-panel panel-glow"><Flame size={25} /><div><span className="eyebrow">SAFETY CORE</span><h2>NO INVENTARÉ ESTADOS</h2><p>ALI mostrará “sin datos” hasta que existan sensores reales. Nunca afirmará que una puerta, luz o clima está bien sin comprobarlo.</p></div></article></section>
  </main>;
}

function HomeGlyph() { return <div className="home-glyph"><span /><span /><span /></div>; }

createRoot(document.getElementById("root")!).render(<App />);
