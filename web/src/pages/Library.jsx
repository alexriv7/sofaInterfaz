import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { onValue, ref } from "firebase/database";
import { db } from "../firebase";

const EXTENSIONS = ["scn", "py", "xml"];

export default function Library() {
  const [examples, setExamples] = useState(null);
  const [query, setQuery] = useState("");
  const [ext, setExt] = useState("");
  const [folder, setFolder] = useState("");

  useEffect(
    () => onValue(ref(db, "sofa_examples"), (snap) => setExamples(snap.val() || {})),
    []
  );

  const list = useMemo(
    () =>
      Object.entries(examples || {})
        .map(([key, ex]) => ({ key, ...ex }))
        .sort((a, b) => a.path.localeCompare(b.path)),
    [examples]
  );
  const folders = useMemo(() => [...new Set(list.map((e) => e.folder.split("/")[0]).filter(Boolean))].sort(), [list]);

  const q = query.trim().toLowerCase();
  const filtered = list.filter(
    (e) =>
      (!ext || e.ext === ext) &&
      (!folder || e.folder === folder || e.folder.startsWith(folder + "/")) &&
      (!q || e.path.toLowerCase().includes(q))
  );

  if (examples === null) return <p className="muted">Cargando biblioteca…</p>;

  return (
    <section>
      <div className="toolbar">
        <input type="search" placeholder="Buscar ejemplo…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={folder} onChange={(e) => setFolder(e.target.value)}>
          <option value="">Todas las carpetas</option>
          {folders.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <select value={ext} onChange={(e) => setExt(e.target.value)}>
          <option value="">Todos los tipos</option>
          {EXTENSIONS.map((x) => <option key={x} value={x}>.{x}</option>)}
        </select>
        <span className="muted">{filtered.length} de {list.length}</span>
      </div>

      {list.length === 0 ? (
        <div className="card">
          <p>La biblioteca está vacía.</p>
          <p className="muted">
            Abre la app de escritorio con una carpeta de ejemplos configurada: al cargar los ejemplos
            los publica automáticamente aquí.
          </p>
        </div>
      ) : (
        <ul className="example-list">
          {filtered.map((e) => (
            <li key={e.key}>
              <Link to={`/ejemplo/${encodeURIComponent(e.key)}`}>
                <span className={`badge ${e.ext}`}>.{e.ext}</span>
                <span className="name">{e.name}</span>
                <span className="muted folder">{e.folder}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
