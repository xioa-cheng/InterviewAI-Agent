<template>
  <!-- 登录页 / 落地页全屏独占，不显示侧边栏 -->
  <router-view v-if="isFullPage" />
  <a-layout v-else class="layout">
    <a-layout-sider :width="210" breakpoint="lg" collapsible class="sider">
      <div class="logo">🎯 InterviewAI</div>
      <a-menu :selected-keys="[activeKey]" @menu-item-click="onMenuClick">
        <a-menu-item key="/interview">🎯 面试模拟</a-menu-item>
        <a-menu-item key="/resume">📄 简历管理</a-menu-item>
        <a-menu-item key="/history">📊 历史记录</a-menu-item>
        <a-menu-item key="/profile">👤 个人资料</a-menu-item>
        <a-menu-item v-if="userStore.isAdmin" key="/admin/users">🛠 用户管理</a-menu-item>
      </a-menu>
      <div class="user-bar">
        <span class="user-name">{{ userStore.displayName }}</span>
        <a-button size="mini" @click="onLogout">退出</a-button>
      </div>
    </a-layout-sider>

    <a-layout>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from './store/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const isFullPage = computed(() => route.name === 'login' || route.name === 'landing')

const activeKey = computed(() => {
  const p = route.path
  if (p.startsWith('/report')) return '/history'
  if (p.startsWith('/resume')) return '/resume'
  if (p.startsWith('/history')) return '/history'
  if (p.startsWith('/profile')) return '/profile'
  if (p.startsWith('/admin')) return '/admin/users'
  if (p.startsWith('/interview')) return '/interview'
  return '/interview'
})

function onMenuClick(key: string) {
  router.push(key)
}

function onLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.layout {
  min-height: 100vh;
}
.sider {
  background: #fff;
  border-right: 1px solid #f0f0f0;
}
.sider :deep(.arco-layout-sider-children) {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  font-weight: 700;
  font-size: 17px;
  color: #165dff;
  border-bottom: 1px solid #f0f0f0;
}
.user-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding: 12px 16px;
  border-top: 1px solid #f0f0f0;
}
.user-name {
  font-size: 13px;
  color: #1d2129;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.content {
  padding: 24px;
  background: #f5f6f8;
}
</style>

<style>
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
</style>
