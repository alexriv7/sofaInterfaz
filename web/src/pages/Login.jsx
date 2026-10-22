import { useState } from "react";
import { useAuth } from "../context/AuthContext";

const ERRORS = {
  "auth/invalid-credential": "Correo o contraseña incorrectos",
  "auth/invalid-email": "Correo no válido",
  "auth/email-already-in-use": "Ya existe una cuenta con ese correo",
  "auth/weak-password": "La contraseña debe tener al menos 6 caracteres",
  "auth/too-many-requests": "Demasiados intentos, prueba más tarde",
};

const isPermissionError = (err) => String(err?.code || err?.message).includes("PERMISSION_DENIED");

export default function Login() {
  const { login, register, resetPassword } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setInfo("");
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, username.trim());
    } catch (err) {
      setError(ERRORS[err.code] || (isPermissionError(err)
        ? "Firebase rechazó el registro (permiso denegado). Revisa que las reglas de database.rules.json estén publicadas."
        : err.message));
    } finally {
      setBusy(false);
    }
  }

  async function onReset() {
    setError("");
    if (!email) return setError("Escribe tu correo para recuperar la contraseña");
    try {
      await resetPassword(email);
      setInfo("Te enviamos un correo para restablecer la contraseña");
    } catch (err) {
      setError(ERRORS[err.code] || err.message);
    }
  }

  const isRegister = mode === "register";
  return (
    <div className="center">
      <form className="card narrow" onSubmit={onSubmit}>
        <h1>SOFA Manager</h1>
        <p className="muted">{isRegister ? "Crear cuenta" : "Iniciar sesión"}</p>
        <label>
          Correo
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        {isRegister && (
          <label>
            Nombre de usuario
            <input value={username} onChange={(e) => setUsername(e.target.value)} required
              pattern="[A-Za-z0-9_\-]{3,32}" title="3-32 caracteres: letras, números, _ o -" />
            <small className="muted">Usa el mismo que en la app de escritorio para compartir tus notas y grupos.</small>
          </label>
        )}
        <label>
          Contraseña
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6}
            autoComplete={isRegister ? "new-password" : "current-password"} />
        </label>
        {error && <p className="error">{error}</p>}
        {info && <p className="ok">{info}</p>}
        <button type="submit" disabled={busy}>{isRegister ? "Registrarme" : "Entrar"}</button>
        <div className="row between">
          <button type="button" className="link" onClick={() => setMode(isRegister ? "login" : "register")}>
            {isRegister ? "Ya tengo cuenta" : "Crear una cuenta"}
          </button>
          {!isRegister && (
            <button type="button" className="link" onClick={onReset}>¿Olvidaste la contraseña?</button>
          )}
        </div>
      </form>
    </div>
  );
}
