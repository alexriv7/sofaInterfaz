import { useState } from "react";
import { get, push, ref, remove, serverTimestamp, set, update } from "firebase/database";
import { db } from "../firebase";
import { useAuth, USERNAME_RE } from "../context/AuthContext";
import { useGroups } from "../context/GroupContext";

// Misma estructura que FirebaseManager.create_group / add_member / remove_member.
export default function Groups() {
  const { username } = useAuth();
  const { myGroups, activeGroupId, setActiveGroupId } = useGroups();
  const [name, setName] = useState("");
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  async function run(fn) {
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err.message);
    }
  }

  function createGroup(e) {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    run(async () => {
      const newRef = push(ref(db, "sofa_groups"));
      await set(newRef, { name: n, owner: username, members: { [username]: true }, created_at: serverTimestamp() });
      setName("");
      setSelected(newRef.key);
    });
  }

  const entries = Object.entries(myGroups).sort((a, b) => a[1].name.localeCompare(b[1].name));
  const group = selected && myGroups[selected];

  return (
    <section className="groups">
      <form className="card row" onSubmit={createGroup}>
        <input placeholder="Nombre del nuevo grupo…" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        <button type="submit" disabled={!name.trim()}>Crear grupo</button>
      </form>
      {error && <p className="error">{error}</p>}

      <div className="split">
        <div className="card">
          <h3>Mis grupos</h3>
          {entries.length === 0 ? (
            <p className="muted">Aún no perteneces a ningún grupo.</p>
          ) : (
            <ul className="group-list">
              {entries.map(([gid, g]) => (
                <li key={gid}>
                  <button className={`item ${selected === gid ? "selected" : ""}`} onClick={() => setSelected(gid)}>
                    <span>{g.name}</span>
                    <span className="muted">
                      {Object.keys(g.members || {}).length} miembros
                      {activeGroupId === gid ? " · activo" : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {group ? (
          <GroupDetail
            key={selected}
            gid={selected}
            group={group}
            username={username}
            active={activeGroupId === selected}
            onActivate={() => setActiveGroupId(activeGroupId === selected ? null : selected)}
            onGone={() => {
              if (activeGroupId === selected) setActiveGroupId(null);
              setSelected(null);
            }}
            run={run}
          />
        ) : (
          <div className="card muted">Selecciona un grupo para ver sus miembros.</div>
        )}
      </div>
    </section>
  );
}

function GroupDetail({ gid, group, username, active, onActivate, onGone, run }) {
  const [member, setMember] = useState("");
  const [notice, setNotice] = useState("");
  const isOwner = group.owner === username;
  const members = Object.keys(group.members || {}).sort();

  function addMember(e) {
    e.preventDefault();
    const m = member.trim();
    setNotice("");
    if (!USERNAME_RE.test(m)) return setNotice("Usuario no válido (3-32 caracteres: letras, números, _ o -)");
    run(async () => {
      await set(ref(db, `sofa_groups/${gid}/members/${m}`), true);
      const hasAccount = (await get(ref(db, `sofa_usernames/${m}`))).exists();
      setMember("");
      if (!hasAccount) setNotice(`"${m}" aún no tiene cuenta web; podrá usar el grupo desde la app de escritorio o al registrarse con ese usuario.`);
    });
  }

  function deleteGroup() {
    if (!confirm(`¿Eliminar el grupo "${group.name}" y todas sus notas?`)) return;
    run(async () => {
      await remove(ref(db, `sofa_group_comments/${gid}`));
      await remove(ref(db, `sofa_groups/${gid}`));
      onGone();
    });
  }

  function leaveGroup() {
    if (!confirm(`¿Salir del grupo "${group.name}"?`)) return;
    run(async () => {
      await remove(ref(db, `sofa_groups/${gid}/members/${username}`));
      onGone();
    });
  }

  return (
    <div className="card">
      <div className="row between">
        <h3>{group.name}</h3>
        <button className={active ? "ghost" : ""} onClick={onActivate}>
          {active ? "Dejar de usar" : "Usar para notas"}
        </button>
      </div>
      <p className="muted">Propietario: {group.owner}</p>

      <h4>Miembros</h4>
      <ul className="member-list">
        {members.map((m) => (
          <li key={m} className="row between">
            <span>{m}{m === group.owner ? " (propietario)" : ""}</span>
            {isOwner && m !== group.owner && (
              <button className="link danger" onClick={() => run(() => update(ref(db, `sofa_groups/${gid}/members`), { [m]: null }))}>
                Quitar
              </button>
            )}
          </li>
        ))}
      </ul>

      {isOwner && (
        <form className="row" onSubmit={addMember}>
          <input placeholder="Usuario a añadir…" value={member} onChange={(e) => setMember(e.target.value)} />
          <button type="submit" disabled={!member.trim()}>Añadir</button>
        </form>
      )}
      {notice && <p className="muted">{notice}</p>}

      <div className="row danger-zone">
        {isOwner ? (
          <button className="danger" onClick={deleteGroup}>Eliminar grupo</button>
        ) : (
          <button className="ghost" onClick={leaveGroup}>Salir del grupo</button>
        )}
      </div>
    </div>
  );
}
