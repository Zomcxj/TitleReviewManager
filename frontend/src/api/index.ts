import axios from 'axios'
import router from '../router'

const api = axios.create({
  baseURL: '',
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_role')
      router.push('/login')
    }
    return Promise.reject(error)
  }
)

export default api
