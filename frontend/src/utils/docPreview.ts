/**
 * Online preview utility for doc / docx files
 *
 * Design notes:
 * 1. Purely frontend local parsing — the docx file is fetched as an ArrayBuffer through a
 *    same-origin API, then parsed into HTML in the browser with mammoth. It never goes through
 *    any third-party online conversion service (e.g. Office Online Viewer / Google Docs
 *    Viewer), so material content (including sensitive data such as ID numbers) never leaves
 *    this domain.
 * 2. XSS protection — the HTML mammoth outputs comes from untrusted document content and must
 *    be sanitized through the DOMPurify whitelist before it may be handed to v-html.
 * 3. mammoth loaded on demand — it is about 575KB, while docx preview is a low-frequency
 *    operation. Switching to a dynamic import splits it into a separate chunk, downloaded only
 *    when the user actually opens a preview, so it no longer weighs down the first screen.
 */
import DOMPurify from 'dompurify'

/** Tags allowed to keep: layout-related only; excludes executable or externally-loading content such as script / iframe / style / object */
const ALLOWED_TAGS = [
  'p', 'br', 'span', 'div', 'hr',
  'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'sub', 'sup',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'colgroup', 'col',
  'blockquote', 'pre', 'code',
  'img', 'a',
]

/**
 * Attributes allowed to keep: no style (avoids CSS injection).
 * src allows the data: protocol for docx-embedded images (DOMPurify only lets data: through on
 * media tags such as img by default).
 */
const ALLOWED_ATTR = [
  'colspan', 'rowspan', 'span', 'align', 'valign', 'width', 'height',
  'src', 'alt', 'title', 'href', 'target', 'rel', 'class',
]

/** Dangerous tags explicitly forbidden */
const FORBID_TAGS = [
  'script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet',
  'link', 'meta', 'base', 'form', 'input', 'button', 'select', 'option', 'textarea',
  'svg', 'math', 'template', 'noscript',
]

/** Sanitize the HTML produced by mammoth, keeping only safe layout tags and attributes */
export function sanitizeDocHtml(rawHtml: string): string {
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    FORBID_TAGS,
    ALLOW_DATA_ATTR: false,
  }) as string
}

/**
 * Parse the ArrayBuffer of a .docx file into a sanitized HTML string.
 * mammoth supports OOXML (.docx) only; the legacy binary .doc format cannot be parsed.
 */
export async function docxToHtml(arrayBuffer: ArrayBuffer): Promise<string> {
  if (!arrayBuffer || arrayBuffer.byteLength === 0) {
    throw new Error('文件内容为空')
  }
  // Dynamic import: mammoth is downloaded only when a docx is actually parsed (see the file header).
  // In the browser mammoth requires arrayBuffer input (its browser field swaps the fs implementation for an in-memory one)
  const { default: mammoth } = await import('mammoth')
  const result = await mammoth.convertToHtml({ arrayBuffer })
  const rawHtml = (result && result.value) || ''
  return sanitizeDocHtml(rawHtml)
}

/** Get the lowercase extension from a filename (dot included); returns an empty string when there is no extension */
export function getFileExt(filename: string): string {
  const name = (filename || '').trim().toLowerCase()
  const idx = name.lastIndexOf('.')
  if (idx <= 0 || idx === name.length - 1) return ''
  return name.slice(idx)
}

/**
 * Fetch material file content same-origin with Cookie authentication.
 * Uses fetch instead of an iframe/new tab, so the content can be parsed directly inside a
 * dialog and no external request is made.
 */
export async function fetchMaterialBuffer(url: string): Promise<ArrayBuffer> {
  const resp = await fetch(url, { credentials: 'include' })
  if (!resp.ok) {
    throw new Error(`获取文件失败: HTTP ${resp.status}`)
  }
  return resp.arrayBuffer()
}
