<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <div class="auth-head">
        <span class="auth-logo">🌟</span>
        <h2>注册账号</h2>
      </div>
      <el-form :model="form" @submit.prevent="onRegister">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名（3-50 位字母/数字/中文/短横线）" size="large">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码（8-64 位）" size="large" show-password>
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.confirm" type="password" placeholder="确认密码" size="large" show-password @keyup.enter="onRegister">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" class="auth-btn" :loading="loading" @click="onRegister">
          注 册
        </el-button>
      </el-form>
      <div class="auth-foot">
        <span>已有账号？<router-link to="/login">返回登录</router-link></span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { register } from '../api/auth'

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '', confirm: '' })

const USERNAME_RE = /^[\w一-龥-]+$/

async function onRegister() {
  if (!form.username || !form.password) return ElMessage.warning('请填写完整信息')
  // 与后端 RegisterIn 规则保持一致，让用户在提交前就能看到明确提示
  if (form.username.length < 3 || form.username.length > 50)
    return ElMessage.warning('用户名长度需为 3-50 位')
  if (!USERNAME_RE.test(form.username))
    return ElMessage.warning('用户名仅支持字母/数字/中文/短横线')
  if (form.password.length < 8 || form.password.length > 64)
    return ElMessage.warning('密码长度需为 8-64 位')
  if (form.password !== form.confirm) return ElMessage.warning('两次输入的密码不一致')
  loading.value = true
  try {
    await register(form.username, form.password)
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page { height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #e8f1ff 0%, #f4f7ff 100%); }
.auth-card { width: 400px; padding: 10px 16px; }
.auth-head { text-align: center; margin-bottom: 18px; }
.auth-logo { font-size: 36px; }
.auth-head h2 { margin: 8px 0 4px; font-size: 19px; color: #303133; }
.auth-btn { width: 100%; }
.auth-foot { text-align: center; margin-top: 14px; font-size: 13px; color: #606266; }
</style>
