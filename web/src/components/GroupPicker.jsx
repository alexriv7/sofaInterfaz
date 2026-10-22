import { useGroups } from "../context/GroupContext";

export default function GroupPicker() {
  const { myGroups, activeGroupId, setActiveGroupId } = useGroups();
  return (
    <label className="group-picker">
      <span className="muted">Notas de:</span>
      <select value={activeGroupId ?? ""} onChange={(e) => setActiveGroupId(e.target.value || null)}>
        <option value="">Global</option>
        {Object.entries(myGroups).map(([gid, g]) => (
          <option key={gid} value={gid}>{g.name}</option>
        ))}
      </select>
    </label>
  );
}
