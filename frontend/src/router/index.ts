import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  { path: '/apply', name: 'CustomerForm', component: () => import('../views/CustomerForm.vue') },
  {
    path: '/admin',
    component: () => import('../components/AdminLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/admin/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'customers', name: 'CustomerList', component: () => import('../views/CustomerList.vue') },
      { path: 'customers/:id', name: 'CustomerDetail', component: () => import('../views/CustomerDetail.vue') },
      { path: 'reviews', name: 'ReviewWorkspace', component: () => import('../views/ReviewWorkspace.vue') },
      { path: 'registration-links', name: 'RegistrationLinks', component: () => import('../views/RegistrationLinks.vue') },
      { path: 'audit-logs', name: 'AuditLog', component: () => import('../views/AuditLog.vue') },
      { path: 'users', name: 'UserList', component: () => import('../views/UserList.vue') },
      { path: 'import', name: 'CustomerImport', component: () => import('../views/CustomerImport.vue') },
      { path: 'transfer', name: 'CustomerTransfer', component: () => import('../views/CustomerTransfer.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('../views/NotFound.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  if (to.meta.requiresAuth) {
    const token = localStorage.getItem('access_token')
    if (!token) {
      next('/login')
    } else {
      next()
    }
  } else {
    next()
  }
})

export default router
