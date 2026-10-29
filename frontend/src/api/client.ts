import axios from 'axios'

export const TOKEN_KEY = 'interviewai_token'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 读取登录态：localStorage 与 sessionStorage 都查（兼容「记住我」两种持久化）
export function readToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

// 请求拦截器：自动附带登录 token
client.interceptors.request.use((config) => {
  try {
    const token = readToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  } catch {
    /* 忽略：存储不可用时仅不附带 token */
  }
  return config
})

// 响应拦截器：token 失效（401）时清除登录态并跳回登录页
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401) {
      try {
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem('interviewai_user')
        sessionStorage.removeItem(TOKEN_KEY)
        sessionStorage.removeItem('interviewai_user')
      } catch {
        /* 忽略 */
      }
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

export default client
