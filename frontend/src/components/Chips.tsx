export default function Chips({ items, empty = "—", tone }: { items: string[]; empty?: string; tone?: "quiet" }) {
  if (items.length === 0) return <span className="soft">{empty}</span>;
  return (
    <ul className={`chips ${tone ?? ""}`}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
