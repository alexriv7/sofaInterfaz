import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { onValue, ref } from "firebase/database";
import { db } from "../firebase";
import Notes from "../components/Notes";

export default function ExampleDetail() {
  const { key } = useParams();
  const [example, setExample] = useState(undefined);

  useEffect(() => onValue(ref(db, `sofa_examples/${key}`), (snap) => setExample(snap.val())), [key]);

  if (example === undefined) return <p className="muted">Cargando…</p>;
  if (!example) {
    return (
      <div className="card">
        <p>Este ejemplo no está en la biblioteca.</p>
        <Link to="/">Volver a la biblioteca</Link>
      </div>
    );
  }

  return (
    <section>
      <Link to="/" className="muted">← Biblioteca</Link>
      <div className="card">
        <h2>{example.name}</h2>
        <p className="muted mono">{example.path}</p>
      </div>
      <Notes examplePath={example.path} />
    </section>
  );
}
