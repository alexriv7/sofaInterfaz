import { createContext, useContext, useEffect, useState } from "react";
import {
  createUserWithEmailAndPassword,
  deleteUser,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut,
} from "firebase/auth";
import { onValue, ref, remove, serverTimestamp, set } from "firebase/database";
import { auth, db } from "../firebase";

const AuthContext = createContext(null);

const isDenied = (err) => String(err?.code || err?.message).includes("PERMISSION_DENIED");

export const USERNAME_RE = /^[A-Za-z0-9_-]{3,32}$/;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = cargando
  const [profile, setProfile] = useState(undefined); // undefined = cargando, null = sin perfil
  const [registering, setRegistering] = useState(false);

  useEffect(() => onAuthStateChanged(auth, (u) => setUser(u ?? null)), []);

  useEffect(() => {
    setProfile(user ? undefined : null);
    if (!user) return;
    return onValue(ref(db, `sofa_users/${user.uid}`), (snap) => setProfile(snap.val()));
  }, [user]);

  async function register(email, password, username) {
    if (!USERNAME_RE.test(username)) {
      throw new Error("El usuario debe tener 3-32 caracteres: letras, números, _ o -");
    }
    // Mientras dura el registro la pantalla de login sigue montada,
    // para que un error no se pierda al cambiar el estado de sesión.
    setRegistering(true);
    try {
      const cred = await createUserWithEmailAndPassword(auth, email, password);
      const usernameRef = ref(db, `sofa_usernames/${username}`);
      let claimed = false;
      try {
        // Primero se reserva el username (la regla rechaza si ya existe);
        // después se crea el perfil, cuya regla comprueba esa reserva.
        await set(usernameRef, cred.user.uid).catch((err) => {
          throw isDenied(err) ? new Error(`El nombre de usuario "${username}" ya está en uso`) : err;
        });
        claimed = true;
        await set(ref(db, `sofa_users/${cred.user.uid}`), {
          username,
          email,
          created_at: serverTimestamp(),
        });
      } catch (err) {
        // Deshacer: liberar el username y borrar la cuenta a medio crear.
        if (claimed) await remove(usernameRef).catch(() => {});
        await deleteUser(cred.user).catch(() => {});
        throw err;
      }
    } finally {
      setRegistering(false);
    }
  }

  const value = {
    user,
    profile,
    username: profile?.username ?? null,
    registering,
    login: (email, password) => signInWithEmailAndPassword(auth, email, password),
    logout: () => signOut(auth),
    resetPassword: (email) => sendPasswordResetEmail(auth, email),
    register,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
