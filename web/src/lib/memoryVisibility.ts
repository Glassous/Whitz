import type { CitationItem } from "../types";

export function isMemoryCitation(item: Pick<CitationItem, "source_type">): boolean {
  return item.source_type === "memory";
}
