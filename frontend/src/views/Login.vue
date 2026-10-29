<template>
  <div class="login-page">
    <!-- 左侧品牌区：大屏展示，移动端隐藏 -->
    <aside class="brand-panel">
      <div class="brand-inner">
        <div class="brand-logo">🎯 InterviewAI</div>
        <h1 class="brand-title">AI 驱动的一对一模拟面试</h1>
        <p class="brand-desc">沉浸式问答、智能评分、个性化报告，帮你在家也能高效备战技术面试。</p>
        <ul class="brand-points">
          <li>🧭 按岗位与行业精准出题</li>
          <li>⚡ 流式实时追问，告别呆板问答</li>
          <li>📈 多维度能力评分与成长建议</li>
          <li>🗂 简历解析 + 题库自管理</li>
        </ul>
      </div>
    </aside>

    <!-- 右侧表单区 -->
    <main class="form-panel">
      <div class="login-card">
        <div class="brand-mobile">🎯 InterviewAI</div>
        <div class="sub">登录后开始你的模拟面试</div>

        <a-tabs v-model:active-key="tab">
          <a-tab-pane key="login" title="登录">
            <a-form :model="loginForm" layout="vertical" @submit="onLogin">
              <a-form-item
                label="邮箱"
                :validate-status="loginErr.email ? 'error' : ''"
                :help="loginErr.email"
              >
                <a-input v-model="loginForm.email" placeholder="you@example.com" allow-clear @input="loginErr.email = ''">
                  <template #prefix><icon-email /></template>
                </a-input>
              </a-form-item>
              <a-form-item
                label="密码"
                :validate-status="loginErr.password ? 'error' : ''"
                :help="loginErr.password"
              >
                <a-input-password v-model="loginForm.password" placeholder="请输入密码" @input="loginErr.password = ''" />
              </a-form-item>
              <div class="row-between">
                <a-checkbox v-model="remember">记住我</a-checkbox>
              </div>
              <a-button type="primary" html-type="submit" long :loading="loading">登录</a-button>
            </a-form>
          </a-tab-pane>

          <a-tab-pane key="register" title="注册">
            <a-form :model="regForm" layout="vertical" @submit="onRegister">
              <a-form-item
                label="用户名"
                :validate-status="regErr.username ? 'error' : ''"
                :help="regErr.username"
              >
                <a-input v-model="regForm.username" placeholder="2~50 个字符" allow-clear @input="regErr.username = ''" />
              </a-form-item>
              <a-form-item
                label="邮箱"
                :validate-status="regErr.email ? 'error' : ''"
                :help="regErr.email"
              >
                <a-input v-model="regForm.email" placeholder="you@example.com" allow-clear @input="regErr.email = ''">
                  <template #prefix><icon-email /></template>
                </a-input>
              </a-form-item>
              <a-form-item
                label="密码"
                :validate-status="regErr.password ? 'error' : ''"
                :help="regErr.password || '至少 6 位'"
              >
                <a-input-password v-model="regForm.password" placeholder="至少 6 位" @input="regErr.password = ''" />
              </a-form-item>
              <a-button type="primary" html-type="submit" long :loading="loading">注册并登录</a-button>
            </a-form>
          </a-tab-pane>
        </a-tabs>
      </div>
      <div class="copyright">© InterviewAI · 让每一次面试都更有准备</div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { useUserStore } from '../store/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const tab = ref<'login' | 'register'>('login')
const loading = ref(false)
const remember = ref(true)
const loginForm = reactive({ email: '', password: '' })
const regForm = reactive({ username: '', email: '', password: '' })
const loginErr = reactive({ email: '', password: '' })
const regErr = reactive({ username: '', email: '', password: '' })

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function goHome() {
  const redirect = (route.query.redirect as string) || '/interview'
  router.push(redirect)
}

// 把后端错误统一转成能看懂的中文提示。
// 后端校验失败(422)时 detail 是数组，直接弹会显示成 [object Object]。
function errMsg(e: any, fallback: string): string {
  const detail = e?.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] || {}
    const loc = Array.isArray(first.loc) ? first.loc : []
    const field = loc[loc.length - 1]
    const label: Record<string, string> = { username: '用户名', email: '邮箱', password: '密码' }
    const name = label[field] || '该项'
    const type = first.type || ''
    if (type.includes('too_short')) return `${name}太短`
    if (type.includes('too_long')) return `${name}太长`
    if (type === 'missing') return `请填写${name}`
    return first.msg || fallback
  }
  return fallback
}

function validateLogin(): boolean {
  loginErr.email = !loginForm.email
    ? '请填写邮箱'
    : EMAIL_RE.test(loginForm.email)
      ? ''
      : '邮箱格式不正确'
  loginErr.password = !loginForm.password
    ? '请填写密码'
    : loginForm.password.length < 6
      ? '密码至少 6 位'
      : ''
  return !loginErr.email && !loginErr.password
}

function validateRegister(): boolean {
  regErr.username = regForm.username.trim().length < 2 ? '用户名至少 2 个字符' : ''
  regErr.email = !regForm.email
    ? '请填写邮箱'
    : EMAIL_RE.test(regForm.email)
      ? ''
      : '邮箱格式不正确'
  regErr.password = regForm.password.length < 6 ? '密码至少 6 位' : ''
  return !regErr.username && !regErr.email && !regErr.password
}

async function onLogin() {
  if (!validateLogin()) return
  loading.value = true
  try {
    await userStore.login(loginForm.email, loginForm.password, remember.value)
    Message.success('登录成功')
    goHome()
  } catch (e: any) {
    Message.error(errMsg(e, '登录失败'))
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  if (!validateRegister()) return
  loading.value = true
  try {
    await userStore.register(
      {
        username: regForm.username,
        email: regForm.email,
        password: regForm.password,
      },
      remember.value,
    )
    Message.success('注册成功，已自动登录')
    goHome()
  } catch (e: any) {
    Message.error(errMsg(e, '注册失败'))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  background: #f5f6f8;
}

/* 左侧品牌区 */
.brand-panel {
  flex: 1 1 52%;
  background: linear-gradient(135deg, #165dff 0%, #4080ff 55%, #6aa1ff 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px;
}
.brand-inner {
  max-width: 460px;
}
.brand-logo {
  font-size: 26px;
  font-weight: 800;
  margin-bottom: 24px;
}
.brand-title {
  font-size: 30px;
  line-height: 1.4;
  font-weight: 700;
  margin: 0 0 16px;
}
.brand-desc {
  font-size: 15px;
  line-height: 1.8;
  opacity: 0.92;
  margin: 0 0 28px;
}
.brand-points {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 14px;
}
.brand-points li {
  font-size: 15px;
  opacity: 0.95;
}

/* 右侧表单区 */
.form-panel {
  flex: 1 1 48%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
}
.login-card {
  width: 380px;
  max-width: 100%;
  background: #fff;
  border-radius: 14px;
  padding: 32px 28px;
  box-shadow: 0 6px 30px rgba(0, 0, 0, 0.08);
}
.brand-mobile {
  display: none;
  font-size: 22px;
  font-weight: 700;
  color: #165dff;
  text-align: center;
}
.sub {
  text-align: center;
  color: #86909c;
  font-size: 13px;
  margin: 6px 0 18px;
}
.row-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.copyright {
  margin-top: 20px;
  font-size: 12px;
  color: #c9cdd4;
}

/* 移动端：隐藏品牌区，表单占满 */
@media (max-width: 768px) {
  .brand-panel {
    display: none;
  }
  .form-panel {
    flex: 1 1 100%;
  }
  .brand-mobile {
    display: block;
    margin-bottom: 8px;
  }
}
</style>
