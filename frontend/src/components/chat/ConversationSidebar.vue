<template>
  <div class="sidebar">
    <div class="brand">
      <span class="brand-logo">🌟</span>
      <span class="brand-name">星辰电商知识库问答</span>
    </div>

    <el-button type="primary" class="new-chat-btn" @click="$emit('new-chat')">
      <el-icon><Plus /></el-icon>&nbsp;新建会话
    </el-button>

    <el-input v-model="keyword" placeholder="搜索会话" clearable size="small" class="search-box">
      <template #prefix><el-icon><Search /></el-icon></template>
    </el-input>

    <div class="conv-list">
      <div
        v-for="c in filtered"
        :key="c.id"
        class="conv-item"
        :class="{ active: c.id === currentId }"
        @click="$emit('select', c.id)"
      >
        <div class="conv-title">{{ c.title }}</div>
        <div class="conv-meta">{{ fmtUTC(c.updated_at) }} · {{ c.message_count }} 条</div>
        <el-dropdown trigger="click" @command="(cmd) => onCommand(cmd, c)" class="conv-menu" @click.stop>
          <el-icon class="more"><MoreFilled /></el-icon>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="rename">重命名</el-dropdown-item>
              <el-dropdown-item command="export">导出 Markdown</el-dropdown-item>
              <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <el-empty v-if="!filtered.length" description="暂无会话" :image-size="60" />
    </div>

    <div class="sidebar-footer">
      <div class="user-info">
        <span class="user-name">{{ auth.user?.username }}</span>
        <el-tag v-if="auth.isAdmin" size="small" type="danger">管理员</el-tag>
      </div>
      <el-dropdown trigger="click" @command="onUserCommand">
        <el-button size="small" text>
          <el-icon><Setting /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">修改密码</el-dropdown-item>
            <el-dropdown-item v-if="auth.isAdmin" command="kb">知识库管理</el-dropdown-item>
            <el-dropdown-item v-if="auth.isAdmin" command="stats">统计看板</el-dropdown-item>
            <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useChatStore } from '../../stores/chat'
import { renameConversation, deleteConversation, exportConversationUrl } from '../../api/chat'
import { fmtUTC } from '../../utils/format'

const props = defineProps({ currentId: { type: Number, default: null } })
defineEmits(['new-chat', 'select'])

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const keyword = ref('')

const filtered = computed(() => {
  if (!keyword.value) return chat.conversations
  return chat.conversations.filter((c) => c.title.includes(keyword.value))
})

onMounted(() => chat.loadConversations().catch(() => {}))

async function onCommand(cmd, conv) {
  if (cmd === 'rename') {
    const { value } = await ElMessageBox.prompt('请输入新标题', '重命名会话', {
      inputValue: conv.title,
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    }).catch(() => ({ value: null }))
    if (value) {
      await renameConversation(conv.id, value)
      chat.loadConversations()
    }
  } else if (cmd === 'export') {
    const token = auth.accessToken
    const resp = await fetch(exportConversationUrl(conv.id), {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!resp.ok) return ElMessage.error('导出失败')
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `会话_${conv.title}.md`
    a.click()
    URL.revokeObjectURL(a.href)
  } else if (cmd === 'delete') {
    await ElMessageBox.confirm(`确定删除会话「${conv.title}」？消息记录将一并删除。`, '删除确认', { type: 'warning' })
    await deleteConversation(conv.id)
    if (chat.currentId === conv.id) chat.startNewChat()
    chat.loadConversations()
    ElMessage.success('已删除')
  }
}

async function onUserCommand(cmd) {
  if (cmd === 'profile') router.push('/profile')
  else if (cmd === 'kb') router.push('/admin/kb')
  else if (cmd === 'stats') router.push('/admin/stats')
  else if (cmd === 'logout') {
    await auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.sidebar { width: 260px; height: 100%; background: #f7f8fa; border-right: 1px solid #e4e7ed; display: flex; flex-direction: column; }
.brand { display: flex; align-items: center; gap: 8px; padding: 16px 14px 8px; font-weight: 700; font-size: 15px; color: #303133; }
.brand-logo { font-size: 22px; }
.new-chat-btn { margin: 8px 14px; }
.search-box { margin: 0 14px 8px; width: auto; }
.conv-list { flex: 1; overflow-y: auto; padding: 0 8px; }
.conv-item { position: relative; padding: 10px 30px 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 2px; }
.conv-item:hover { background: #eceef2; }
.conv-item.active { background: #e0edff; }
.conv-title { font-size: 13.5px; color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: #a8abb2; margin-top: 3px; }
.conv-menu { position: absolute; right: 6px; top: 10px; }
.more { color: #c0c4cc; font-size: 14px; }
.conv-item:hover .more { color: #606266; }
.sidebar-footer { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-top: 1px solid #e4e7ed; }
.user-info { display: flex; gap: 6px; align-items: center; }
.user-name { font-size: 13px; color: #303133; font-weight: 600; }
</style>
