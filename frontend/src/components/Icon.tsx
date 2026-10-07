/** Small stroke icon set (24×24), replaces the emoji the UI used to rely on. */
const PATHS = {
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  stop: "M7 7h10v10H7z",
  play: "M8 5.5v13l10.5-6.5z",
  speaker: "M4 9.5v5h3.5L12 18.5v-13L7.5 9.5zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11",
  headphones: "M4 15v-3a8 8 0 0 1 16 0v3M4 15a2 2 0 0 1 2-2h1v7H6a2 2 0 0 1-2-2zM20 15a2 2 0 0 0-2-2h-1v7h1a2 2 0 0 0 2-2z",
  plus: "M12 5v14M5 12h14",
  back: "M15 5l-7 7 7 7",
  forward: "M9 5l7 7-7 7",
  check: "M5 12.5l4.5 4.5L19 7.5",
  close: "M6 6l12 12M18 6L6 18",
  refresh: "M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4",
  trash: "M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12",
  upload: "M12 16V4M7 9l5-5 5 5M5 20h14",
  clock: "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  send: "M4.5 12h13M12.5 6l6 6-6 6",
  today: "M4 12h3l2.5-6 5 12 2.5-6h3",
  drills: "M5 4.5h10a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10",
  history: "M4 6h16M4 12h16M4 18h10",
  errors: "M12 4l9 16H3zM12 10v4M12 17v.5",
  resume: "M7 3.5h7l4 4V20.5H7zM14 3.5v4h4M10 12h5M10 15.5h5",
  jobs: "M4 8h16v11H4zM9 8V5.5h6V8M4 13h16",
  settings: "M5 7h9M18 7h1M5 17h3M12 17h7M16 5v4M10 15v4",
  new: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  coach: "M5 5h14v10H10l-5 4z",
  chevron: "M8 10l4 4 4-4",
} as const;

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 18, title }: { name: IconName; size?: number; title?: string }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title && <title>{title}</title>}
      <path d={PATHS[name]} fill={name === "play" || name === "stop" ? "currentColor" : "none"} />
    </svg>
  );
}
