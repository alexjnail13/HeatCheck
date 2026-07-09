import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import client from "../api/client";
import { saveToken } from "../auth/auth";
import "./Auth.css";

function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    if (loading) return;
    setError(null);
    setLoading(true);

    try {
      // 1. Create the account (backend returns the new user, no token).
      await client.post("/auth/signup", { email, password });
      // 2. Immediately log in to get a token, so signup drops you straight in.
      const res = await client.post("/auth/login", { email, password });
      saveToken(res.data.access_token);
      navigate("/");
    } catch (err) {
      // Surface the backend's message (e.g. "Email already registered").
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not create account.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <h1 className="auth-title">Sign up</h1>

        {error && <p className="auth-error">{error}</p>}

        <label className="auth-label">
          Email
          <input
            className="auth-input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </label>

        <label className="auth-label">
          Password
          <input
            className="auth-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="new-password"
          />
        </label>

        <button className="auth-button" type="submit" disabled={loading}>
          {loading ? "Creating account…" : "Sign up"}
        </button>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  );
}

export default SignupPage;
