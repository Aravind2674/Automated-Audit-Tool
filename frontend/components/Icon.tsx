/** Material Symbols glyph -- the icon set used throughout the design system. */
export default function Icon({ name, filled = false, className = "" }: {
  name: string; filled?: boolean; className?: string;
}) {
  return (
    <span className={`material-symbols-outlined ${filled ? "fill" : ""} ${className}`}>
      {name}
    </span>
  );
}
