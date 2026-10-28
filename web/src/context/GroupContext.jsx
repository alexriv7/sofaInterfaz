import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { onValue, ref } from "firebase/database";
import { db } from "../firebase";
import { useAuth } from "./AuthContext";

const GroupContext = createContext(null);
const STORAGE_KEY = "sofa_active_group";

export function GroupProvider({ children }) {
  const { username } = useAuth();
  const [allGroups, setAllGroups] = useState({});
  const [activeGroupId, setActiveGroupIdState] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (!username) return;
    return onValue(ref(db, "sofa_groups"), (snap) => setAllGroups(snap.val() || {}));
  }, [username]);

  // Igual que FirebaseManager.get_my_groups: grupos donde soy miembro.
  const myGroups = useMemo(() => {
    const mine = {};
    for (const [gid, g] of Object.entries(allGroups)) {
      if (username && g?.members?.[username]) mine[gid] = g;
    }
    return mine;
  }, [allGroups, username]);

  const activeGroup = activeGroupId ? myGroups[activeGroupId] : null;

  function setActiveGroupId(gid) {
    setActiveGroupIdState(gid);
    try {
      if (gid) localStorage.setItem(STORAGE_KEY, gid);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* almacenamiento no disponible */
    }
  }

  const value = {
    myGroups,
    // Si el grupo guardado ya no existe o me sacaron, se vuelve a Global.
    activeGroupId: activeGroup ? activeGroupId : null,
    activeGroup,
    setActiveGroupId,
  };
  return <GroupContext.Provider value={value}>{children}</GroupContext.Provider>;
}

export const useGroups = () => useContext(GroupContext);
