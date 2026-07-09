import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { isLoggedIn, logout } from "../auth/auth";
import "./Navbar.css";

function Navbar() {
  const navigate = useNavigate();
  useLocation(); // re-render on route change so auth state stays fresh

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <nav className="navbar">
      <NavLink to="/" className="navbar-brand">
        🔥 Heat Check
      </NavLink>
      <div className="navbar-links">
        <NavLink
          to="/"
          className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          end
        >
          Home
        </NavLink>
        <NavLink
          to="/standings"
          className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
        >
          Standings
        </NavLink>
        <NavLink
          to="/ask"
          className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
        >
          Ask Heat Check
        </NavLink>
        {isLoggedIn() ? (
          <button className="nav-link nav-logout" onClick={handleLogout}>
            Log out
          </button>
        ) : (
          <NavLink
            to="/login"
            className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          >
            Log in
          </NavLink>
        )}
      </div>
    </nav>
  );
}

export default Navbar;