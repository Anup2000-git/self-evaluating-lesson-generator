import { useCallback, useEffect, useState } from "react";

/**
 * Width of an element, kept current with a ResizeObserver (charts redraw to fit).
 * Uses a callback ref so it also works when the element mounts later than the component
 * (e.g. a chart that first renders an empty state and only then its canvas).
 */
export function useElementWidth<T extends HTMLElement>(fallback = 600) {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);
  const ref = useCallback((element: T | null) => setNode(element), []);

  useEffect(() => {
    if (!node) return;
    setWidth(node.clientWidth || fallback);
    const observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [node, fallback]);

  return { ref, width };
}
