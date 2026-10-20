import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../store/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/Login.vue'),
    },
    {
      path: '/',
      name: 'interview',
      component: () => import('../views/Interview.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/report/:id',
      name: 'report',
      component: () => import('../views/Report.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/resume',
      name: 'resume',
      component: () => import('../views/Resume.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('../views/History.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/profile',
      name: 'profile',
      component: () => import('../views/Profile.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('../views/UserAdmin.vue'),
      meta: { requiresAuth: true },
    },
  ],
})

// 全局守卫：未登录只能访问登录页，已登录访问登录页则回首页
let authChecked = false

router.beforeEach(async (to) => {
  const userStore = useUserStore()
  // 首次导航时，若本地存有 token，先向后端确认其是否仍有效，
  // 避免「旧 token 失效却仍被当成已登录、点开始面试才报未登录」
  if (!authChecked) {
    authChecked = true
    if (userStore.token) {
      await userStore.checkAuth()
    }
  }
  if (to.meta.requiresAuth && !userStore.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && userStore.isLoggedIn) {
    return { name: 'interview' }
  }
  return true
})

export default router
