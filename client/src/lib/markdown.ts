/**
 * Markdown conversion utilities
 * Simple regex-based conversions for common markdown syntax
 */

/**
 * Convert markdown to HTML for TipTap editor
 */
export function markdownToHTML(markdown: string): string {
  if (!markdown) return "";

  // Simple regex-based conversion for common markdown syntax
  let html = markdown;

  // Headings
  html = html.replace(/^### (.*?)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.*?)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.*?)$/gm, "<h1>$1</h1>");

  // Bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Lists
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");
  html = html.replace(/<\/ul>\n<ul>/g, "");

  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => {
    if (!match.includes("<ul>")) {
      return "<ol>" + match + "</ol>";
    }
    return match;
  });
  html = html.replace(/<\/ol>\n<ol>/g, "");

  // Images (must come before links since they use similar syntax)
  html = html.replace(/!\[([^\]]*)\]\((.+?)\)/g, '<img src="$2" alt="$1">');

  // Links
  html = html.replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>');

  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]+?)```/g, "<pre><code>$2</code></pre>");

  // Inline code
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");

  // Paragraphs
  html = html.split("\n\n").map(para => {
    if (!para.match(/^<[huopl]/)) {
      return `<p>${para}</p>`;
    }
    return para;
  }).join("\n");

  return html;
}

/**
 * Convert HTML from TipTap editor to markdown
 */
export function htmlToMarkdown(html: string): string {
  if (!html) return "";

  let markdown = html;

  // Headings
  markdown = markdown.replace(/<h1>(.*?)<\/h1>/g, "# $1\n\n");
  markdown = markdown.replace(/<h2>(.*?)<\/h2>/g, "## $1\n\n");
  markdown = markdown.replace(/<h3>(.*?)<\/h3>/g, "### $1\n\n");

  // Bold and italic
  markdown = markdown.replace(/<strong><em>(.*?)<\/em><\/strong>/g, "***$1***");
  markdown = markdown.replace(/<em><strong>(.*?)<\/strong><\/em>/g, "***$1***");
  markdown = markdown.replace(/<strong>(.*?)<\/strong>/g, "**$1**");
  markdown = markdown.replace(/<b>(.*?)<\/b>/g, "**$1**");
  markdown = markdown.replace(/<em>(.*?)<\/em>/g, "*$1*");
  markdown = markdown.replace(/<i>(.*?)<\/i>/g, "*$1*");

  // Lists
  markdown = markdown.replace(/<ul>\s*<li>(.*?)<\/li>\s*<\/ul>/gs, (match) => {
    return match.replace(/<li>(.*?)<\/li>/g, "- $1\n");
  });
  markdown = markdown.replace(/<ol>\s*<li>(.*?)<\/li>\s*<\/ol>/gs, (match) => {
    let counter = 1;
    return match.replace(/<li>(.*?)<\/li>/g, () => `${counter++}. $1\n`);
  });

  // Images (must come before links to avoid conflicts)
  markdown = markdown.replace(/<img[^>]+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>/g, "![$2]($1)");
  markdown = markdown.replace(/<img[^>]+src="([^"]+)"[^>]*>/g, "![]($1)");

  // Links
  markdown = markdown.replace(/<a href="(.+?)">(.*?)<\/a>/g, "[$2]($1)");

  // Code blocks
  markdown = markdown.replace(/<pre><code>([\s\S]+?)<\/code><\/pre>/g, "```\n$1\n```\n\n");

  // Inline code
  markdown = markdown.replace(/<code>(.*?)<\/code>/g, "`$1`");

  // Paragraphs
  markdown = markdown.replace(/<p>(.*?)<\/p>/g, "$1\n\n");

  // Clean up excessive newlines
  markdown = markdown.replace(/\n{3,}/g, "\n\n");

  return markdown.trim();
}
