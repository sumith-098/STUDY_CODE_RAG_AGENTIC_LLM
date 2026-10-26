// FileTree -- project ki files ka tree (folders indent ke saath).
// Props: files [{path,size}], selected (path), onSelect(path)
import { FileCode2, Folder } from "lucide-react";

export default function FileTree({ files, selected, onSelect }) {
  const rows = [];
  const seenDirs = new Set();
  [...files].sort((a, b) => a.path.localeCompare(b.path)).forEach(f => {
    const parts = f.path.split("/");
    for (let i = 0; i < parts.length - 1; i++) {          // is file ke folders (jo pehle na dikhe ho)
      const dir = parts.slice(0, i + 1).join("/");
      if (!seenDirs.has(dir)) { seenDirs.add(dir); rows.push({ key: `d:${dir}`, dir: true, name: parts[i], depth: i }); }
    }
    rows.push({ key: `f:${f.path}`, name: parts[parts.length - 1], depth: parts.length - 1, path: f.path, size: f.size });
  });

  if (rows.length === 0) return <p className="empty-files tree-empty">Files will appear here.</p>;
  return (
    <div className="file-tree">
      {rows.map(r => r.dir
        ? <div key={r.key} className="tree-row dir" style={{ paddingLeft: 10 + r.depth * 14 }}><Folder size={14} />{r.name}</div>
        : <button key={r.key} className={`tree-row file ${r.path === selected ? "active" : ""}`}
                  style={{ paddingLeft: 10 + r.depth * 14 }} onClick={() => onSelect(r.path)} title={r.path}>
            <FileCode2 size={14} /><span>{r.name}</span><small>{r.size >= 1024 ? `${(r.size / 1024).toFixed(1)}k` : r.size}</small>
          </button>)}
    </div>
  );
}