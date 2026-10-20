import axios from 'axios'

export const TOKEN_KEY = 'interviewai_token'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

// 请求拦截器：自动附带登录 token
client.interceptors.request.use((config) => {
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  } catch {
    /* 忽略：localStorage 不可用时仅不附带 token */
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
