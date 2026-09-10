import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/register', name: 'register', component: () => import('../views/RegisterView.vue') },
  { path: '/', name: 'chat', component: () => import('../views/ChatView.vue'), meta: { requiresAuth: true } },
  { path: '/profile', name: 'profile', component: () => import('../views/ProfileView.vue'), meta: { requiresAuth: true } },
  { path: '/admin/kb', name: 'kb-manage', component: () => import('../views/admin/KbManageView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/admin/stats', name: 'stats', component: () => import('../views/admin/StatsView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/403', name: 'forbidden', component: () => import('../views/NotFoundView.vue'), meta: { forbidden: true } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录 → /login；非管理员访问管理页 → /403
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { name: 'forbidden' }
  }
  if ((to.name === 'login' || to.name === 'register') && auth.isLoggedIn) {
    return { name: 'chat' }
  }
  return true
})

export default router
