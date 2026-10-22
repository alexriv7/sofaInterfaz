import { useEffect, useMemo, useState } from "react";
import { onValue, push, ref, remove, serverTimestamp, set, update } from "firebase/database";
import { db } from "../firebase";
import { useAuth } from "../context/AuthContext";
import { useGroups } from "../context/GroupContext";
import { commentsPath, formatDate } from "../lib/paths";

// Mismo formato que FirebaseManager.save_comment en la app de escritorio.
export default function Notes({ examplePath }) {
  const { username } = useAuth();
  const { activeGroupId, activeGroup } = useGroups();
  const [comments, setComments] = useState(null);
  const [error, setError] = useState("");
  const basePath = commentsPath(examplePath, activeGroupId);

  useEffect(() => {
    setComments(null);
    return onValue(
      ref(db, basePath),
      (snap) => setComments(snap.val() || {}),
      (err) => setError(err.message)
    );
  }, [basePath]);

  const { roots, replies } = useMemo(() => {
    const all = Object.entries(comments || {})
      .map(([id, c]) => ({ id, ...c }))
      .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
    const ids = new Set(all.map((c) => c.id));
    const replies = {};
    const roots = [];
    for (const c of all) {
      if (c.parent_id && ids.has(c.parent_id)) (replies[c.parent_id] ||= []).push(c);
      else roots.push(c);
    }
    return { roots, replies };
  }, [comments]);

  async function run(fn) {
    setError("");
    try {
      await fn();
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    }
  }

  const add = (text, parentId = null) =>
    run(() =>
      set(push(ref(db, basePath)), {
        user: username,
        text,
        timestamp: serverTimestamp(),
        original_path: examplePath,
        parent_id: parentId,
      })
    );
  const edit = (id, text) =>
    run(() => update(ref(db, `${basePath}/${id}`), { text, edited_timestamp: serverTimestamp() }));
  const del = (id) => {
    if (confirm("¿Borrar esta nota?")) run(() => remove(ref(db, `${basePath}/${id}`)));
  };

  return (
    <div className="card">
      <h3>
        Notas <span className="muted">· {activeGroup ? `grupo ${activeGroup.name}` : "globales"}</span>
      </h3>
      {error && <p className="error">{error}</p>}
      {comments === null ? (
        <p className="muted">Cargando notas…</p>
      ) : roots.length === 0 ? (
        <p className="muted">Todavía no hay notas para este ejemplo.</p>
      ) : (
        <ul className="notes">
          {roots.map((c) => (
            <li key={c.id}>
              <Note c={c} mine={c.user === username} onEdit={edit} onDelete={del} onReply={(t) => add(t, c.id)} />
              {replies[c.id] && (
                <ul className="notes replies">
                  {replies[c.id].map((r) => (
                    <li key={r.id}>
                      <Note c={r} mine={r.user === username} onEdit={edit} onDelete={del} />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      <Composer onSubmit={(t) => add(t)} placeholder="Escribe una nota…" />
    </div>
  );
}

function Note({ c, mine, onEdit, onDelete, onReply }) {
  const [mode, setMode] = useState(null); // "edit" | "reply" | null
  return (
    <div className="note">
      <div className="note-head">
        <strong>{c.user}</strong>
        <span className="muted">
          {formatDate(c.timestamp)}
          {c.edited_timestamp ? " (editado)" : ""}
        </span>
      </div>
      {mode === "edit" ? (
        <Composer
          initial={c.text}
          submitLabel="Guardar"
          onCancel={() => setMode(null)}
          onSubmit={async (t) => (await onEdit(c.id, t)) && setMode(null)}
        />
      ) : (
        <p className="note-text">{c.text}</p>
      )}
      {mode === null && (
        <div className="row">
          {onReply && <button className="link" onClick={() => setMode("reply")}>Responder</button>}
          {mine && <button className="link" onClick={() => setMode("edit")}>Editar</button>}
          {mine && <button className="link danger" onClick={() => onDelete(c.id)}>Borrar</button>}
        </div>
      )}
      {mode === "reply" && (
        <Composer
          placeholder={`Responder a ${c.user}…`}
          submitLabel="Responder"
          onCancel={() => setMode(null)}
          onSubmit={async (t) => (await onReply(t)) && setMode(null)}
        />
      )}
    </div>
  );
}

function Composer({ initial = "", placeholder, submitLabel = "Publicar", onSubmit, onCancel }) {
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setBusy(true);
    const ok = await onSubmit(t);
    setBusy(false);
    if (ok && !initial) setText("");
  }
  return (
    <form className="composer" onSubmit={submit}>
      <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} rows={2} maxLength={5000} />
      <div className="row">
        <button type="submit" disabled={busy || !text.trim()}>{submitLabel}</button>
        {onCancel && <button type="button" className="ghost" onClick={onCancel}>Cancelar</button>}
      </div>
    </form>
  );
}
