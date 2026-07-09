import { useState } from "react";
import client from "../api/client";
import "./AskHeatCheck.css";

function AskHeatCheck() {
  // The conversation: an array of { role: "user" | "assistant", text }.
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    // Steps 1-3 (synchronous, before the network call): show the user's message
    // immediately, clear the input, and start the "thinking" indicator.
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setLoading(true);

    try {
      // Step 4: ask the backend, then append the bot's reply.
      const res = await client.post("/chat", { message: text });
      setMessages((prev) => [...prev, { role: "assistant", text: res.data.reply }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "Sorry — I couldn't reach Heat Check just now." },
      ]);
    } finally {
      // Step 5: thinking indicator off.
      setLoading(false);
    }
  }

  return (
    <div className="ask-page">
      <header className="ask-header">
        <h1 className="ask-title">Ask Heat Check</h1>
        <p className="ask-subtitle">Your NBA analytics assistant</p>
      </header>

      <div className="chat-log">
        {messages.length === 0 && (
          <p className="chat-empty">Ask me about NBA stats, standings, or matchups.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role}`}>
            {m.text}
          </div>
        ))}
        {loading && <div className="chat-bubble assistant thinking">Thinking…</div>}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Heat Check…"
        />
        <button className="chat-send" type="submit" disabled={loading}>
          Send
        </button>
      </form>
    </div>
  );
}

export default AskHeatCheck;
