import { Navigate, Route, Routes } from "react-router-dom";
import { firebaseConfigured } from "./firebase";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { GroupProvider } from "./context/GroupContext";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Library from "./pages/Library";
import ExampleDetail from "./pages/ExampleDetail";
import Groups from "./pages/Groups";

function Protected({ children }) {
  const { user, profile, logout } = useAuth();
  if (user === undefined || (user && profile === undefined)) {
    return <div className="center muted">Cargando…</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!profile) {
    return (
      <div className="center card narrow">
        <p>Tu cuenta no tiene perfil de usuario (el registro no terminó). Crea la cuenta de nuevo.</p>
        <button onClick={logout}>Salir</button>
      </div>
    );
  }
  return children;
}

function AppRoutes() {
  const { user } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route
        element={
          <Protected>
            <GroupProvider>
              <Layout />
            </GroupProvider>
          </Protected>
        }
      >
        <Route index element={<Library />} />
        <Route path="ejemplo/:key" element={<ExampleDetail />} />
        <Route path="grupos" element={<Groups />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  if (!firebaseConfigured) {
    return (
      <div className="center card narrow">
        <h2>Falta configurar Firebase</h2>
        <p>
          Copia <code>web/.env.example</code> como <code>web/.env</code>, rellena los datos de tu
          app web de Firebase y reinicia <code>npm run dev</code>.
        </p>
      </div>
    );
  }
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
