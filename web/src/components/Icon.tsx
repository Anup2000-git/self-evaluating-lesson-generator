// A small inline-SVG icon set (no icon font, no extra dependency).
const PATHS: Record<string, string> = {
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.8 2.8M14.9 14.9l2.8 2.8M6.3 17.7l2.8-2.8M14.9 9.1l2.8-2.8",
  runs: "M4 6h16M4 12h16M4 18h10",
  lab: "M9 3h6M10 3v6l-5.5 9.2A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.8L14 9V3M7.5 15h9",
  brain: "M9.5 4a2.5 2.5 0 0 0-2.4 3.1A3 3 0 0 0 5 10c0 1 .5 1.9 1.2 2.4A3 3 0 0 0 9 17h.5v3M14.5 4a2.5 2.5 0 0 1 2.4 3.1A3 3 0 0 1 19 10c0 1-.5 1.9-1.2 2.4A3 3 0 0 1 15 17h-.5v3M12 4v16",
  rubric: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  book: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 21V5M8 7h7M8 11h5",
  server: "M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01",
  check: "M5 12.5 10 17l9-10",
  x: "M6 6l12 12M18 6 6 18",
  play: "M8 5v14l11-7z",
  tool: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  send: "M4 12 20 4l-6 16-3-7z",
  thought: "M7 18a4 4 0 0 1-.8-7.9A5 5 0 0 1 16 8.5a4 4 0 0 1 1 7.5H7zM6 21h.01M9 20h.01",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  alert: "M12 3 2 20h20zM12 10v4M12 17h.01",
  info: "M12 8h.01M11 12h1v5h1M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  coin: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM14.5 9.5a2.5 2 0 0 0-2.5-1.5c-1.4 0-2.5.8-2.5 2s1.1 1.6 2.5 2 2.5.8 2.5 2-1.1 2-2.5 2a2.5 2 0 0 1-2.5-1.5M12 6.5v1.5M12 16v1.5",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  copy: "M9 9h10v12H9zM5 15V3h10",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
  arrow: "M5 12h14M13 6l6 6-6 6",
  thumbUp: "M7 10v11H3V10zM7 10l4-7a2 2 0 0 1 2 2v4h6a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 17.6 21H7",
  thumbDown: "M17 14V3h4v11zM17 14l-4 7a2 2 0 0 1-2-2v-4H5a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 6.4 3H17",
  stop: "M6 6h12v12H6z",
  doc: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h7M9 17h7",
  memory: "M12 2a4 4 0 0 1 4 4v1a4 4 0 0 1 2 7.5V18a4 4 0 0 1-6 3.5A4 4 0 0 1 6 18v-3.5A4 4 0 0 1 8 7V6a4 4 0 0 1 4-4z",
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, title }: { name: IconName; size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      <path d={PATHS[name]} />
    </svg>
  );
}
