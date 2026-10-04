import { createRouter, createWebHistory } from 'vue-router'
import { getSession } from '../api/request.js'

const routes = [
  { path: '/login', component: () => import('../views/login.vue') },
  { path: '/forbidden', component: () => import('../views/forbidden.vue'), meta: { requiresAuth: true } },
  { path: '/admin/bookings', component: () => import('../views/admin_dashboard/booking_manage.vue'), meta: { requiresAuth: true, admin: true } },
  { path: '/admin/schedule', component: () => import('../views/admin_dashboard/schedule_manage.vue'), meta: { requiresAuth: true, admin: true } },
  { path: '/admin/export', component: () => import('../views/admin_dashboard/data_export.vue'), meta: { requiresAuth: true, admin: true } },
  { path: '/admin/duty-history', component: () => import('../views/admin_dashboard/duty_history.vue'), meta: { requiresAuth: true, admin: true } },
  { path: '/admin/duty-terminal', component: () => import('../views/admin_dashboard/duty_terminal.vue'), meta: { requiresAuth: true, admin: true } },
  { path: '/admin/appeals', component: () => import('../views/appeal_audit/appeal_list.vue'), meta: { requiresAuth: true, admin: true } },
  { path: '/duty/rooms', component: () => import('../views/duty_console/room_radar.vue'), meta: { requiresAuth: true, duty: true } },
  { path: '/duty/handover', component: () => import('../views/duty_console/handover.vue'), meta: { requiresAuth: true, duty: true } },
  { path: '/duty/print', component: () => import('../views/duty_console/print_center.vue'), meta: { requiresAuth: true, duty: true } },
  { path: '/', redirect: () => homeFor(getSession()) },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

function homeFor(session) {
  if (!session) return '/login'
  if (session.role === 'admin') return '/admin/bookings'
  if (session.mode === 'duty') return '/duty/handover'
  return '/forbidden'
}

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const session = getSession()
  if (to.meta.requiresAuth && !session) return '/login'
  if (to.path === '/login' && session) return homeFor(session)
  if (to.meta.admin && session?.role !== 'admin') return homeFor(session)
  if (to.meta.duty && !(session?.mode === 'duty' || session?.role === 'admin')) return homeFor(session)
  return true
})

export default router
