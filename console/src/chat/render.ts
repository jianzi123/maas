import { marked } from "marked";
import DOMPurify from "dompurify";
export function renderMarkdown(value: string) {
  return DOMPurify.sanitize(
    marked.parse(value, { async: false, gfm: true, breaks: true }) as string,
    {
      USE_PROFILES: { html: true },
      FORBID_TAGS: ["img", "style", "iframe", "form", "input", "button"],
      FORBID_ATTR: ["style"],
    },
  );
}
