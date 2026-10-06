export default function Chips({ items, empty = "—" }: { items: string[]; empty?: string }) {
  if (items.length === 0) return <span className="muted">{empty}</span>;
  return (
    <ul className="chips">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
