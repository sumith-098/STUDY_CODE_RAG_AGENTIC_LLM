// Mark -- StudyPilot ka apna chhota logo: gol ring ke andar serif italic "S" (monogram).
// Props: size (px, default 24). Rang CSS se aata hai (.mark -> accent colour).
export default function Mark({ size = 24 }) {
  return <span className="mark" style={{ width: size, height: size, fontSize: Math.round(size * 0.6) }} aria-hidden="true">S</span>;
}