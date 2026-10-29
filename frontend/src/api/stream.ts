// SSE 流式请求工具：用 fetch + ReadableStream 消费后端 text/event-stream。
// 之所以不用 EventSource，是因为它只支持 GET；面试出题/提交需要 POST body。
import { TOKEN_KEY } from './client'

export interface SSEEvent {
  type: string
  [key: string]: any
}

/**
 * 发送一个 POST 请求并把响应体当作 SSE 逐事件回调。
 * @param url    后端路径，如 /api/v1/stream/start
 * @param body   请求体
 * @param onEvent 每解析到一个 data 事件时的回调
 * @param signal 可传入 AbortSignal 取消
 */
export async function streamPost(
  url: string,
  body: any,
  onEvent: (e: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY) || ''
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok || !res.body) {
    let detail = `请求失败(${res.status})`
    try {
      const j = await res.json()
      detail = j?.detail || detail
    } catch {
      /* 忽略解析失败 */
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  const emit = (raw: string) => {
    // 取 data: 开头的那一行（SSE 允许多行，这里简单取首个 data 行）
    const dataLine = raw
      .split('\n')
      .map((l) => l.trim())
      .find((l) => l.startsWith('data:'))
    if (!dataLine) return
    const payload = dataLine.slice(5).trim()
    if (!payload) return
    try {
      onEvent(JSON.parse(payload))
    } catch {
      /* 忽略非法 JSON */
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      emit(raw)
    }
  }
  if (buf.trim()) emit(buf)
}
