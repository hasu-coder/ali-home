import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, Brain, Cat, Home, Lightbulb, MessageCircle, Shield, Users, Zap } from "lucide-react";
import { apiGet, apiPost } from "./api/client";
import "./styles/app.css";

type UserProfile = { username: string; display_name: string; role: string };
type Room = { key: string; name: string; floor: string; has_voice_point: boolean };
type Pet = { key: string; name: string; species: string; home_state: string; last_known_room?: string | null };
type ActivityItem = { id: number; event_type: string; summary: string; actor?: string; level: number; created_at: string };
type Usage = { daily_spend: number; monthly_spend: number; daily_limit: number; monthly_limit: number; enabled: boolean };
type Health = { status: string; service: string };

function StatCard({ icon, label, value, meta }: { icon: React.ReactNode; label: string; value: string; meta?: string }) {
  return (
    <section className="stat-card">
      <div className="stat-icon">{icon}</div>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        {meta ? <span>{meta}</span> : null}
      </div>
    </section>
  );
}

function App() {
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [pets, setPets] = useState<Pet[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [input, setInput] = useState("ALI, enciende la cocina");
  const [reply, setReply] = useState("");

  async function refresh() {
    const [nextHealth, nextUsers, nextRooms, nextPets, nextActivity, nextUsage] = await Promise.all([
      apiGet<Health>("/api/health"),
      apiGet<UserProfile[]>("/api/users"),
      apiGet<Room[]>("/api/rooms"),
      apiGet<Pet[]>("/api/pets"),
      apiGet<ActivityItem[]>("/api/activity"),
      apiGet<Usage>("/api/usage/openai")
    ]);
    setHealth(nextHealth);
    setUsers(nextUsers);
    setRooms(nextRooms);
    setPets(nextPets);
    setActivity(nextActivity);
    setUsage(nextUsage);
  }

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  const voiceRooms = useMemo(() => rooms.filter((room) => room.has_voice_point), [rooms]);

  async function askAli() {
    const result = await apiPost<{ response: string; used_remote_llm: boolean; estimated_cost: number }>("/api/ask", {
      text: input,
      probable_user: "ismael",
      room_key: "cocina_salon"
    });
    setReply(`${result.response}${result.used_remote_llm ? ` · GPT ${result.estimated_cost.toFixed(5)} EUR aprox.` : " · Local"}`);
    await refresh();
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>ALI</h1>
          <p>Asistente de Laura e Ismael</p>
        </div>
        <div className="runtime-pill">{health?.status === "ok" ? "ALI Core online" : "ALI Core unavailable"} · Local-first</div>
      </header>

      <section className="grid stats">
        <StatCard icon={<Users size={20} />} label="Personas" value={users.map((u) => u.display_name).join(" · ")} meta="perfiles locales" />
        <StatCard icon={<Cat size={20} />} label="Gato" value={pets[0]?.home_state || "Sin datos"} meta={pets[0]?.last_known_room || "ubicación pendiente"} />
        <StatCard icon={<Home size={20} />} label="Habitaciones" value={`${rooms.length}`} meta={`${voiceRooms.length} puntos de voz previstos`} />
        <StatCard icon={<Zap size={20} />} label="GPT" value={`${usage?.monthly_spend.toFixed(4) ?? "0.0000"} €`} meta={`límite ${usage?.monthly_limit ?? 0} €/mes`} />
      </section>

      <section className="panel command-panel">
        <div>
          <h2><Brain size={20} /> ALI Core</h2>
          <p>Prueba inicial de enrutado local/GPT. Los comandos conocidos no usan GPT.</p>
        </div>
        <div className="command-row">
          <input value={input} onChange={(event) => setInput(event.target.value)} />
          <button onClick={askAli}>Enviar</button>
        </div>
        {reply ? <div className="reply"><MessageCircle size={18} /> {reply}</div> : null}
      </section>

      <section className="dashboard-grid">
        <div className="panel">
          <h2><Lightbulb size={20} /> Habitaciones</h2>
          <div className="room-list">
            {rooms.map((room) => (
              <article key={room.key} className="room-row">
                <span>{room.name}</span>
                <small>{room.floor}{room.has_voice_point ? " · voz" : ""}</small>
              </article>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2><Activity size={20} /> ALI Activity</h2>
          <div className="activity-list">
            {activity.map((item) => (
              <article key={item.id}>
                <strong>{item.event_type}</strong>
                <p>{item.summary}</p>
                <small>{new Date(item.created_at).toLocaleString()}</small>
              </article>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2><Shield size={20} /> Safety Core</h2>
          <p className="muted">Reservado para la siguiente fase funcional. Debe ejecutarse localmente aunque GPT o Internet no estén disponibles.</p>
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
