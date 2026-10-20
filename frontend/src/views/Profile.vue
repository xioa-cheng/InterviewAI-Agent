<template>
  <div>
    <a-page-header title="👤 个人资料" subtitle="完善你的求职信息，面试出题会更贴合" />

    <a-row :gutter="16">
      <!-- 基本资料 -->
      <a-col :span="12">
        <a-card title="基本资料" class="card">
          <a-descriptions :column="1" bordered size="medium" style="margin-bottom: 20px">
            <a-descriptions-item label="用户名">{{ userStore.user?.username }}</a-descriptions-item>
            <a-descriptions-item label="邮箱">{{ userStore.user?.email }}</a-descriptions-item>
          </a-descriptions>

          <a-form :model="form" layout="vertical">
            <a-form-item label="姓名">
              <a-input v-model="form.full_name" placeholder="例如：张三" />
            </a-form-item>
            <a-form-item label="目标岗位">
              <a-input v-model="form.target_position" placeholder="例如：后端开发工程师" />
            </a-form-item>
            <a-form-item label="行业">
              <a-input v-model="form.industry" placeholder="例如：互联网 / 金融 / 电商" />
            </a-form-item>
            <a-form-item label="经验水平">
              <a-input v-model="form.experience_level" placeholder="例如：初级 / 中级 / 高级" />
            </a-form-item>
            <a-button type="primary" long :loading="saving" @click="saveProfile">保存资料</a-button>
          </a-form>
        </a-card>
      </a-col>

      <!-- 修改密码 -->
      <a-col :span="12">
        <a-card title="修改密码" class="card">
          <a-form :model="pwdForm" layout="vertical">
            <a-form-item label="原密码">
              <a-input-password v-model="pwdForm.old_password" placeholder="请输入原密码" />
            </a-form-item>
            <a-form-item label="新密码">
              <a-input-password v-model="pwdForm.new_password" placeholder="至少 6 位" />
            </a-form-item>
            <a-form-item label="确认新密码">
              <a-input-password v-model="pwdForm.confirm" placeholder="再次输入新密码" />
            </a-form-item>
            <a-button long :loading="pwdSaving" @click="changePassword">更新密码</a-button>
          </a-form>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import client from '../api/client'
import { useUserStore } from '../store/user'

const userStore = useUserStore()

const saving = ref(false)
const pwdSaving = ref(false)
const form = reactive({ full_name: '', target_position: '', industry: '', experience_level: '' })
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

async function loadProfile() {
  try {
    const res = await client.get('/auth/me')
    const u = res.data
    form.full_name = u.full_name || ''
    form.target_position = u.target_position || ''
    form.industry = u.industry || ''
    form.experience_level = u.experience_level || ''
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '加载资料失败')
  }
}

async function saveProfile() {
  saving.value = true
  try {
    await client.patch('/users/me', {
      full_name: form.full_name || null,
      target_position: form.target_position || null,
      industry: form.industry || null,
      experience_level: form.experience_level || null,
    })
    Message.success('资料已保存')
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function changePassword() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    Message.warning('请填写原密码和新密码')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    Message.warning('两次输入的新密码不一致')
    return
  }
  if (pwdForm.new_password.length < 6) {
    Message.warning('新密码至少 6 位')
    return
  }
  pwdSaving.value = true
  try {
    await client.post('/users/me/password', {
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password,
    })
    Message.success('密码已更新')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm = ''
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '修改密码失败')
  } finally {
    pwdSaving.value = false
  }
}

onMounted(loadProfile)
</script>

<style scoped>
.card {
  height: 100%;
}
</style>
