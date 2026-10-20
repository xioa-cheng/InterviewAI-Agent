<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">🎯 InterviewAI</div>
      <div class="sub">AI 面试模拟 · 登录后开始练习</div>

      <a-tabs v-model:active-key="tab">
        <a-tab-pane key="login" title="登录">
          <a-form :model="loginForm" layout="vertical" @submit="onLogin">
            <a-form-item label="邮箱">
              <a-input v-model="loginForm.email" placeholder="you@example.com" />
            </a-form-item>
            <a-form-item label="密码">
              <a-input-password v-model="loginForm.password" placeholder="请输入密码" />
            </a-form-item>
            <a-button type="primary" html-type="submit" long :loading="loading">登录</a-button>
          </a-form>
        </a-tab-pane>

        <a-tab-pane key="register" title="注册">
          <a-form :model="regForm" layout="vertical" @submit="onRegister">
            <a-form-item label="用户名">
              <a-input v-model="regForm.username" placeholder="2~50 个字符" />
            </a-form-item>
            <a-form-item label="邮箱">
              <a-input v-model="regForm.email" placeholder="you@example.com" />
            </a-form-item>
            <a-form-item label="密码">
              <a-input-password v-model="regForm.password" placeholder="至少 6 位" />
            </a-form-item>
            <a-button type="primary" html-type="submit" long :loading="loading">注册并登录</a-button>
          </a-form>
        </a-tab-pane>
      </a-tabs>
    </div>
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
const loginForm = reactive({ email: '', password: '' })
const regForm = reactive({ username: '', email: '', password: '' })

function goHome() {
  const redirect = (route.query.redirect as string) || '/'
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

async function onLogin() {
  if (!loginForm.email || !loginForm.password) {
    Message.warning('请填写邮箱和密码')
    return
  }
  loading.value = true
  try {
    await userStore.login(loginForm.email, loginForm.password)
    Message.success('登录成功')
    goHome()
  } catch (e: any) {
    Message.error(errMsg(e, '登录失败'))
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  if (!regForm.username || !regForm.email || !regForm.password) {
    Message.warning('请填写完整信息')
    return
  }
  loading.value = true
  try {
    await userStore.register({
      username: regForm.username,
      email: regForm.email,
      password: regForm.password,
    })
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
  align-items: center;
  justify-content: center;
  background: #f5f6f8;
  padding: 16px;
}
.login-card {
  width: 380px;
  max-width: 100%;
  background: #fff;
  border-radius: 12px;
  padding: 32px 28px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}
.brand {
  font-size: 22px;
  font-weight: 700;
  color: #165dff;
  text-align: center;
}
.sub {
  text-align: center;
  color: #86909c;
  font-size: 13px;
  margin: 6px 0 20px;
}
</style>
