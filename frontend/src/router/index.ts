import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  {
    path: '/change-password',
    name: 'ChangePassword',
    component: () => import('../views/ChangePassword.vue'),
    meta: { requiresAuth: true },
  },
  { path: '/apply', name: 'CustomerForm', component: () => import('../views/CustomerForm.vue') },
  { path: '/progress', name: 'ProgressQuery', component: () => import('../views/ProgressQuery.vue') },
  {
    path: '/admin',
    component: () => import('../components/AdminLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/admin/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'customers', name: 'CustomerList', component: () => import('../views/CustomerList.vue') },
      { path: 'customers/:id', name: 'CustomerDetail', component: () => import('../views/CustomerDetail.vue') },
      { path: 'reviews', name: 'ReviewWorkspace', component: () => import('../views/ReviewWorkspace.vue'), meta: { roles: ['admin', 'reviewer'] } },
      { path: 'registration-links', name: 'RegistrationLinks', component: () => import('../views/RegistrationLinks.vue'), meta: { roles: ['admin', 'salesman'] } },
      { path: 'public-pool', name: 'PublicPool', component: () => import('../views/PublicPool.vue'), meta: { roles: ['admin', 'salesman'] } },
      { path: 'audit-logs', name: 'AuditLog', component: () => import('../views/AuditLog.vue'), meta: { roles: ['admin'] } },
      { path: 'users', name: 'UserList', component: () => import('../views/UserList.vue'), meta: { roles: ['admin'] } },
      { path: 'import', name: 'CustomerImport', component: () => import('../views/CustomerImport.vue'), meta: { roles: ['admin', 'salesman'] } },
      { path: 'transfer', name: 'CustomerTransfer', component: () => import('../views/CustomerTransfer.vue'), meta: { roles: ['admin'] } },
      { path: 'finance', name: 'Finance', component: () => import('../views/Finance.vue'), meta: { roles: ['admin', 'salesman'] } },
      { path: 'system-config', name: 'SystemConfig', component: () => import('../views/SystemConfig.vue'), meta: { roles: ['admin'] } },
      { path: 'recycle-bin', name: 'RecycleBin', component: () => import('../views/RecycleBin.vue'), meta: { roles: ['admin'] } },
      { path: 'backup', name: 'Backup', component: () => import('../views/Backup.vue'), meta: { roles: ['admin'] } },
    ],
  },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('../views/NotFound.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('access_token')

  // 强制改密拦截：已登录且被标记必须改密时，只允许停留在改密页或登录页
  if (token && localStorage.getItem('must_change_password') === '1') {
    if (to.path !== '/change-password' && to.path !== '/login') {
      next('/change-password')
      return
    }
  }

  if (to.meta.requiresAuth) {
    if (!token) {
      next('/login')
      return
    }
    // 角色权限检查
    const requiredRoles = to.meta.roles as string[] | undefined
    if (requiredRoles && requiredRoles.length > 0) {
      const userStr = localStorage.getItem('user_role')
      const userRole = userStr || ''
      if (!requiredRoles.includes(userRole)) {
        next('/admin/dashboard')
        return
      }
    }
  }
  next()
})

export default router
