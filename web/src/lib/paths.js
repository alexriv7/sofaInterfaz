// Debe coincidir exactamente con FirebaseManager._normalize_path (firebase_handler.py)
// para que la web y la app de escritorio lean/escriban las mismas notas.
export function normalizePath(path) {
  return path
    .replaceAll("\\", "_slash_")
    .replaceAll(".", "_dot_")
    .replaceAll("#", "_hash_")
    .replaceAll("$", "_dollar_")
    .replaceAll("[", "_lbracket_")
    .replaceAll("]", "_rbracket_")
    .replaceAll("/", "_fwslash_");
}

export function commentsPath(examplePath, groupId) {
  const safe = normalizePath(examplePath);
  return groupId ? `sofa_group_comments/${groupId}/${safe}` : `sofa_comments/${safe}`;
}

export function splitPath(examplePath) {
  const parts = examplePath.split(/[\\/]/);
  const name = parts.pop();
  return { name, folder: parts.join("/") };
}

export function formatDate(ts) {
  if (!ts || typeof ts !== "number") return "";
  return new Date(ts).toLocaleString("es", { dateStyle: "short", timeStyle: "short" });
}
