<template>
  <div class="customer-form-page" v-loading="validating">
    <div class="form-header">
      <div class="form-brand">
        <div class="brand-icon">
          <el-icon :size="24"><Memo /></el-icon>
        </div>
        <div>
          <h2>职称申报信息登记</h2>
          <p v-if="tokenValid">由业务员 {{ salesmanName }} 为您提供专属申报服务</p>
          <p v-else-if="tokenError" class="error-text">{{ tokenError }}</p>
          <p v-else>请填写您的个人信息，后续将由业务员协助完成材料准备</p>
        </div>
      </div>
    </div>

    <el-alert v-if="tokenValid" type="success" :closable="false" show-icon class="security-notice">
      <template #title>安全提示</template>
      您正在使用专属注册链接提交信息，您的申报将自动分配给对应业务员跟进。此链接已启用防篡改和时效性保护。
    </el-alert>

    <el-card class="form-card" v-if="!tokenError">
      <el-form :model="form" :rules="rules" ref="formRef" label-position="top" label-width="120px">
        <div class="form-section">
          <div class="section-header">
            <el-icon color="#6366f1"><User /></el-icon>
            <h3>身份信息</h3>
          </div>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="姓名" prop="name">
                <el-input v-model="form.name" placeholder="请输入姓名" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="身份证号" prop="id_number">
                <el-input v-model="form.id_number" placeholder="18位身份证号" maxlength="18" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="手机号" prop="phone">
                <el-input v-model="form.phone" placeholder="请输入手机号" maxlength="11" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="学历" prop="education">
                <el-select v-model="form.education" placeholder="请选择学历" style="width: 100%">
                  <el-option label="高中及以下" value="高中及以下" />
                  <el-option label="中专/技校" value="中专/技校" />
                  <el-option label="大专" value="大专" />
                  <el-option label="本科" value="本科" />
                  <el-option label="硕士研究生" value="硕士研究生" />
                  <el-option label="博士研究生" value="博士研究生" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="现职称" prop="current_title">
                <el-select v-model="form.current_title" placeholder="请选择现职称" style="width: 100%">
                  <el-option label="无" value="无" />
                  <el-option label="技术员" value="技术员" />
                  <el-option label="助理工程师" value="助理工程师" />
                  <el-option label="工程师" value="工程师" />
                  <el-option label="主治医师" value="主治医师" />
                  <el-option label="讲师" value="讲师" />
                  <el-option label="助理研究员" value="助理研究员" />
                  <el-option label="其他" value="其他" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="取得现职称年份">
                <el-input-number v-model="form.current_title_year" :min="1980" :max="2026"
                  placeholder="年份" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="form-section">
          <div class="section-header">
            <el-icon color="#6366f1"><OfficeBuilding /></el-icon>
            <h3>工作信息</h3>
          </div>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="工作单位">
                <el-input v-model="form.work_unit" placeholder="请输入工作单位全称" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="职务">
                <el-input v-model="form.position" placeholder="请输入职务" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="专业技术工作年限">
                <el-input-number v-model="form.professional_years" :min="0" :max="50"
                  placeholder="年" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="form-section">
          <div class="section-header">
            <el-icon color="#6366f1"><Briefcase /></el-icon>
            <h3>项目经历</h3>
          </div>
          <div v-for="(proj, idx) in projects" :key="idx" class="project-item">
            <el-card shadow="never" class="project-card">
              <template #header>
                <div class="project-header">
                  <span class="project-title">项目 {{ idx + 1 }}</span>
                  <el-button v-if="projects.length > 1" type="danger" text size="small" @click="removeProject(idx)">
                    <el-icon><Delete /></el-icon> 删除
                  </el-button>
                </div>
              </template>
              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="项目名称">
                    <el-input v-model="proj.name" placeholder="项目名称" />
                  </el-form-item>
                </el-col>
                <el-col :span="6">
                  <el-form-item label="起始时间">
                    <el-date-picker v-model="proj.start_date" type="month" placeholder="开始" value-format="YYYY-MM"
                      style="width: 100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="6">
                  <el-form-item label="结束时间">
                    <el-date-picker v-model="proj.end_date" type="month" placeholder="结束" value-format="YYYY-MM"
                      style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="16">
                <el-col :span="8">
                  <el-form-item label="本人角色">
                    <el-input v-model="proj.role" placeholder="如：项目负责人" />
                  </el-form-item>
                </el-col>
                <el-col :span="16">
                  <el-form-item label="简要描述">
                    <el-input v-model="proj.description" type="textarea" :rows="2" placeholder="简要描述项目内容和贡献" />
                  </el-form-item>
                </el-col>
              </el-row>
            </el-card>
          </div>
          <el-button type="primary" plain @click="addProject" class="add-project-btn">
            <el-icon><Plus /></el-icon> 添加项目经历
          </el-button>
        </div>

        <el-form-item class="submit-section">
          <el-button type="primary" size="large" :loading="submitting" @click="handleSubmit" class="submit-btn">
            提交申报信息
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-dialog v-model="successVisible" title="提交成功" width="420px" :close-on-click-modal="false">
      <el-result icon="success" title="您的申报信息已成功提交"
        sub-title="业务员将尽快与您联系，协助您完成后续材料准备">
      </el-result>
      <template #footer>
        <el-button type="primary" @click="successVisible = false">我知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'
import { ElMessage } from 'element-plus'

const route = useRoute()
const formRef = ref()
const submitting = ref(false)
const successVisible = ref(false)
const validating = ref(false)
const tokenValid = ref(false)
const tokenError = ref('')
const salesmanName = ref('')

const form = reactive({
  name: '',
  id_number: '',
  phone: '',
  education: '',
  current_title: '',
  current_title_year: undefined as number | undefined,
  work_unit: '',
  position: '',
  professional_years: undefined as number | undefined,
})

interface Project {
  name: string
  start_date: string
  end_date: string
  role: string
  description: string
}

const projects = ref<Project[]>([{ name: '', start_date: '', end_date: '', role: '', description: '' }])

const rules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  id_number: [
    { required: true, message: '请输入身份证号', trigger: 'blur' },
    { pattern: /^\d{17}[\dXx]$/, message: '请输入正确的18位身份证号', trigger: 'blur' },
  ],
  phone: [
    { pattern: /^1[3-9]\d{9}$/, message: '请输入正确的手机号', trigger: 'blur' },
  ],
  education: [{ required: true, message: '请选择学历', trigger: 'change' }],
  current_title: [{ required: true, message: '请选择现职称', trigger: 'change' }],
}

const token = route.query.token as string || ''

onMounted(async () => {
  if (token) {
    validating.value = true
    try {
      const { data } = await api.get(`/api/registration-links/validate/${token}`)
      tokenValid.value = true
      salesmanName.value = data.salesman_name
    } catch (e: any) {
      tokenError.value = e.response?.data?.detail || '注册链接无效'
    } finally {
      validating.value = false
    }
  }
})

function addProject() {
  projects.value.push({ name: '', start_date: '', end_date: '', role: '', description: '' })
}
function removeProject(idx: number) {
  if (projects.value.length > 1) {
    projects.value.splice(idx, 1)
  }
}

async function handleSubmit() {
  await formRef.value?.validate()
  submitting.value = true
  try {
    if (token && tokenValid.value) {
      await api.post('/api/registration-links/self-register', {
        token,
        ...form,
        project_experiences: JSON.stringify(projects.value.filter(p => p.name)),
      })
    } else {
      await api.post('/api/customers/', {
        ...form,
        project_experiences: JSON.stringify(projects.value.filter(p => p.name)),
      })
    }
    successVisible.value = true
    resetForm()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交失败，请重试')
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  form.name = ''
  form.id_number = ''
  form.phone = ''
  form.education = ''
  form.current_title = ''
  form.current_title_year = undefined
  form.work_unit = ''
  form.position = ''
  form.professional_years = undefined
  projects.value = [{ name: '', start_date: '', end_date: '', role: '', description: '' }]
}
</script>

<style scoped>
.customer-form-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px 16px 60px;
}
.form-header {
  margin-bottom: 24px;
}
.form-brand {
  display: flex;
  align-items: center;
  gap: 16px;
}
.brand-icon {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.form-brand h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
}
.form-brand p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 14px;
}
.error-text {
  color: #ef4444 !important;
  font-weight: 500;
}
.security-notice {
  margin-bottom: 20px;
  border-radius: 10px;
}
.form-card {
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.form-section {
  margin-bottom: 24px;
}
.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid #f1f5f9;
}
.section-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}
.project-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  margin-bottom: 12px;
}
.project-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.project-title {
  font-weight: 600;
  font-size: 14px;
}
.add-project-btn {
  width: 100%;
  border-style: dashed;
}
.submit-section {
  margin-top: 32px;
}
.submit-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  border-radius: 10px;
}
</style>
