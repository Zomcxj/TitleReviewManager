/**
 * doc / docx 在线预览工具
 *
 * 设计要点：
 * 1. 纯前端本地解析 —— docx 文件通过同源接口取回 ArrayBuffer 后，直接在浏览器内用 mammoth
 *    解析成 HTML，全程不经过任何第三方在线转换服务（如 Office Online Viewer / Google Docs
 *    Viewer），材料内容（含身份证等敏感信息）不会离开本域。
 * 2. XSS 防护 —— mammoth 输出的 HTML 来自不可信文档内容，必须经 DOMPurify 白名单净化后
 *    才允许交给 v-html 渲染。
 * 3. mammoth 按需加载 —— 它约 575KB，而预览 docx 是低频操作。改为动态 import 后
 *    该依赖被拆成独立 chunk，只在用户真正点开预览时才下载，不再拖累首屏。
 */
import DOMPurify from 'dompurify'

/** 允许保留的标签：仅排版相关，排除 script / iframe / style / object 等可执行或可外联内容 */
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
 * 允许保留的属性：不含 style（避免 CSS 注入）。
 * src 允许 data: 协议，用于展示 docx 内嵌图片（DOMPurify 默认仅对 img 等媒体标签放行 data:）。
 */
const ALLOWED_ATTR = [
  'colspan', 'rowspan', 'span', 'align', 'valign', 'width', 'height',
  'src', 'alt', 'title', 'href', 'target', 'rel', 'class',
]

/** 显式禁止的危险标签 */
const FORBID_TAGS = [
  'script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet',
  'link', 'meta', 'base', 'form', 'input', 'button', 'select', 'option', 'textarea',
  'svg', 'math', 'template', 'noscript',
]

/** 净化 mammoth 产出的 HTML，仅保留安全的排版标签与属性 */
export function sanitizeDocHtml(rawHtml: string): string {
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    FORBID_TAGS,
    ALLOW_DATA_ATTR: false,
  }) as string
}

/**
 * 将 .docx 文件的 ArrayBuffer 解析为净化后的 HTML 字符串。
 * mammoth 仅支持 OOXML（.docx），旧版二进制 .doc 无法解析。
 */
export async function docxToHtml(arrayBuffer: ArrayBuffer): Promise<string> {
  if (!arrayBuffer || arrayBuffer.byteLength === 0) {
    throw new Error('文件内容为空')
  }
  // 动态导入：mammoth 只在真正解析 docx 时才下载（见文件头说明）。
  // mammoth 在浏览器端依赖 arrayBuffer 输入（其 browser 字段会把 fs 实现替换为内存实现）
  const { default: mammoth } = await import('mammoth')
  const result = await mammoth.convertToHtml({ arrayBuffer })
  const rawHtml = (result && result.value) || ''
  return sanitizeDocHtml(rawHtml)
}

/** 从文件名取小写扩展名（含点）；无扩展名时返回空串 */
export function getFileExt(filename: string): string {
  const name = (filename || '').trim().toLowerCase()
  const idx = name.lastIndexOf('.')
  if (idx <= 0 || idx === name.length - 1) return ''
  return name.slice(idx)
}

/**
 * 带 Cookie 鉴权、同源取回材料文件内容。
 * 使用 fetch 而非 iframe/新标签页，便于在弹窗内直接解析，且不产生外部请求。
 */
export async function fetchMaterialBuffer(url: string): Promise<ArrayBuffer> {
  const resp = await fetch(url, { credentials: 'include' })
  if (!resp.ok) {
    throw new Error(`获取文件失败: HTTP ${resp.status}`)
  }
  return resp.arrayBuffer()
}
