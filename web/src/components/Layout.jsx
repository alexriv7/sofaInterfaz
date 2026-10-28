import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import GroupPicker from "./GroupPicker";

export default function Layout() {
  const { username, logout } = useAuth();
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">SOFA Manager</span>
        <nav>
          <NavLink to="/" end>Biblioteca</NavLink>
          <NavLink to="/grupos">Grupos</NavLink>
        </nav>
        <div className="spacer" />
        <GroupPicker />
        <span className="muted user">{username}</span>
        <button className="ghost" onClick={logout}>Salir</button>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
