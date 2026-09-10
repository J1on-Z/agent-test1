<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <div class="auth-head">
        <span class="auth-logo">🌟</span>
        <h2>星辰电商知识库智能问答系统</h2>
        <p>基于 LangChain + LangGraph 的企业级 RAG 问答</p>
      </div>
      <el-form :model="form" @submit.prevent="onLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password @keyup.enter="onLogin">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" class="auth-btn" :loading="loading" @click="onLogin">
          登 录
        </el-button>
      </el-form>
      <div class="auth-foot">
        <span>还没有账号？<router-link to="/register">立即注册</router-link></span>
        <el-text size="small" type="info">演示账号：admin / 123456</el-text>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function onLogin() {
  if (!form.username || !form.password) return ElMessage.warning('请输入用户名和密码')
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push(route.query.redirect || '/')
  } catch (e) {
    const msg = e.response?.data?.message
    ElMessage.error(msg || '登录失败，请检查用户名密码')
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
.auth-head p { color: #909399; font-size: 13px; margin: 0; }
.auth-btn { width: 100%; }
.auth-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; font-size: 13px; color: #606266; }
</style>
