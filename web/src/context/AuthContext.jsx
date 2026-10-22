import { createContext, useContext, useEffect, useState } from "react";
import {
  createUserWithEmailAndPassword,
  deleteUser,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut,
} from "firebase/auth";
import { onValue, ref, serverTimestamp, set } from "firebase/database";
import { auth, db } from "../firebase";

const AuthContext = createContext(null);

export const USERNAME_RE = /^[A-Za-z0-9_-]{3,32}$/;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = cargando
  const [profile, setProfile] = useState(undefined); // undefined = cargando, null = sin perfil

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
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    try {
      // Primero se reserva el username (la regla rechaza si ya existe);
      // después se crea el perfil, cuya regla comprueba esa reserva.
      await set(ref(db, `sofa_usernames/${username}`), cred.user.uid);
      await set(ref(db, `sofa_users/${cred.user.uid}`), {
        username,
        email,
        created_at: serverTimestamp(),
      });
    } catch (err) {
      await deleteUser(cred.user).catch(() => {});
      throw err.code === "PERMISSION_DENIED"
        ? new Error("Ese nombre de usuario ya está en uso")
        : err;
    }
  }

  const value = {
    user,
    profile,
    username: profile?.username ?? null,
    login: (email, password) => signInWithEmailAndPassword(auth, email, password),
    logout: () => signOut(auth),
    resetPassword: (email) => sendPasswordResetEmail(auth, email),
    register,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
