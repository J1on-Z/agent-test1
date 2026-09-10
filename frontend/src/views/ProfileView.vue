<template>
  <div class="profile-page">
    <el-card class="profile-card">
      <template #header>
        <div class="card-head">
          <span>修改密码</span>
          <el-button link @click="$router.push('/')">← 返回问答</el-button>
        </div>
      </template>
      <el-form :model="form" label-width="90px" style="max-width: 420px">
        <el-form-item label="当前用户">
          <el-text>{{ auth.user?.username }}（{{ auth.user?.role === 'admin' ? '管理员' : '普通用户' }}）</el-text>
        </el-form-item>
        <el-form-item label="原密码">
          <el-input v-model="form.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.newPassword" type="password" show-password placeholder="至少 8 位，含字母和数字" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="form.confirm" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="onSubmit">修改密码</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { changePassword } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ oldPassword: '', newPassword: '', confirm: '' })

async function onSubmit() {
  if (!form.oldPassword || !form.newPassword) return ElMessage.warning('请填写完整')
  if (form.newPassword !== form.confirm) return ElMessage.warning('两次输入的新密码不一致')
  loading.value = true
  try {
    await changePassword(form.oldPassword, form.newPassword)
    ElMessage.success('密码修改成功，请重新登录')
    auth.clear()
    router.push('/login')
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '修改失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.profile-page { height: 100vh; display: flex; align-items: center; justify-content: center; background: #f2f3f7; }
.profile-card { width: 520px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
</style>
