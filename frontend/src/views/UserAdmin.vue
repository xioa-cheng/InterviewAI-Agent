<template>
  <div>
    <a-page-header title="🛠 用户管理" subtitle="查看和管理所有注册用户">
      <template #extra>
        <a-button type="primary" @click="openCreate">新建用户</a-button>
      </template>
    </a-page-header>

    <a-card class="card">
      <a-spin :loading="loading">
        <a-table :data="list" :columns="columns" :pagination="false" row-key="id" />
      </a-spin>
    </a-card>

    <!-- 新建用户 -->
    <a-modal v-model:visible="showCreate" title="新建用户" :ok-loading="saving" @ok="createUser" @cancel="showCreate = false">
      <a-form :model="createForm" layout="vertical">
        <a-form-item label="用户名">
          <a-input v-model="createForm.username" placeholder="2~50 个字符" />
        </a-form-item>
        <a-form-item label="邮箱">
          <a-input v-model="createForm.email" placeholder="you@example.com" />
        </a-form-item>
        <a-form-item label="密码">
          <a-input-password v-model="createForm.password" placeholder="至少 6 位" />
        </a-form-item>
        <a-form-item label="角色">
          <a-radio-group v-model="createForm.role" type="button">
            <a-radio value="user">普通用户</a-radio>
            <a-radio value="admin">管理员</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="姓名（可选）">
          <a-input v-model="createForm.full_name" placeholder="例如：张三" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 编辑用户 -->
    <a-modal
      v-model:visible="showEdit"
      :title="'编辑用户 - ' + editForm.username"
      :ok-loading="saving"
      @ok="updateUser"
      @cancel="showEdit = false"
    >
      <a-form :model="editForm" layout="vertical">
        <a-form-item label="角色">
          <a-radio-group v-model="editForm.role" type="button">
            <a-radio value="user">普通用户</a-radio>
            <a-radio value="admin">管理员</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="启用状态">
          <a-switch v-model="editForm.is_active" />
        </a-form-item>
        <a-form-item label="姓名">
          <a-input v-model="editForm.full_name" placeholder="例如：张三" />
        </a-form-item>
        <a-form-item label="目标岗位">
          <a-input v-model="editForm.target_position" placeholder="例如：后端开发工程师" />
        </a-form-item>
        <a-form-item label="行业">
          <a-input v-model="editForm.industry" placeholder="例如：互联网" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 重置密码 -->
    <a-modal
      v-model:visible="showReset"
      :title="'重置密码 - ' + resetForm.username"
      :ok-loading="saving"
      @ok="resetPassword"
      @cancel="showReset = false"
    >
      <a-form :model="resetForm" layout="vertical">
        <a-form-item label="新密码">
          <a-input-password v-model="resetForm.new_password" placeholder="至少 6 位" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, reactive, ref } from 'vue'
import { Button, Message, Modal, Tag } from '@arco-design/web-vue'
import client from '../api/client'

const list = ref<any[]>([])
const loading = ref(false)
const saving = ref(false)

const showCreate = ref(false)
const showEdit = ref(false)
const showReset = ref(false)

const createForm = reactive({ username: '', email: '', password: '', role: 'user', full_name: '' })
const editForm = reactive({
  id: '',
  username: '',
  role: 'user',
  is_active: true,
  full_name: '',
  target_position: '',
  industry: '',
})
const resetForm = reactive({ id: '', username: '', new_password: '' })

const columns = [
  { title: '用户名', dataIndex: 'username' },
  { title: '邮箱', dataIndex: 'email' },
  { title: '姓名', render: ({ record }: any) => record.full_name || '-' },
  {
    title: '角色',
    width: 90,
    render: ({ record }: any) =>
      record.role === 'admin'
        ? h(Tag, { color: 'red' }, () => '管理员')
        : h(Tag, { color: 'gray' }, () => '普通用户'),
  },
  {
    title: '状态',
    width: 90,
    render: ({ record }: any) =>
      record.is_active
        ? h(Tag, { color: 'green' }, () => '启用')
        : h(Tag, { color: 'orange' }, () => '禁用'),
  },
  { title: '注册时间', width: 160, render: ({ record }: any) => formatTime(record.created_at) },
  {
    title: '操作',
    width: 230,
    render: ({ record }: any) =>
      h('span', [
        h(Button, { type: 'text', size: 'small', onClick: () => openEdit(record) }, () => '编辑'),
        h(Button, { type: 'text', size: 'small', onClick: () => openReset(record) }, () => '重置密码'),
        h(
          Button,
          { type: 'text', size: 'small', status: 'danger', onClick: () => delUser(record) },
          () => '删除',
        ),
      ]),
  },
]

async function loadList() {
  loading.value = true
  try {
    const res = await client.get('/admin/users')
    list.value = res.data
  } catch (e: any) {
    list.value = []
    Message.error(e?.response?.data?.detail || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  showCreate.value = true
}

async function createUser(): Promise<boolean> {
  if (!createForm.username.trim() || !createForm.email.trim() || !createForm.password) {
    Message.warning('请填写用户名、邮箱和密码')
    return false
  }
  saving.value = true
  try {
    await client.post('/admin/users', {
      username: createForm.username,
      email: createForm.email,
      password: createForm.password,
      role: createForm.role,
      full_name: createForm.full_name || null,
    })
    Message.success('已创建用户')
    showCreate.value = false
    createForm.username = ''
    createForm.email = ''
    createForm.password = ''
    createForm.role = 'user'
    createForm.full_name = ''
    await loadList()
    return true
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '创建失败')
    return false
  } finally {
    saving.value = false
  }
}

function openEdit(record: any) {
  editForm.id = record.id
  editForm.username = record.username
  editForm.role = record.role
  editForm.is_active = record.is_active
  editForm.full_name = record.full_name || ''
  editForm.target_position = record.target_position || ''
  editForm.industry = record.industry || ''
  showEdit.value = true
}

async function updateUser(): Promise<boolean> {
  saving.value = true
  try {
    await client.patch(`/admin/users/${editForm.id}`, {
      role: editForm.role,
      is_active: editForm.is_active,
      full_name: editForm.full_name || null,
      target_position: editForm.target_position || null,
      industry: editForm.industry || null,
    })
    Message.success('已更新用户')
    showEdit.value = false
    await loadList()
    return true
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '更新失败')
    return false
  } finally {
    saving.value = false
  }
}

function openReset(record: any) {
  resetForm.id = record.id
  resetForm.username = record.username
  resetForm.new_password = ''
  showReset.value = true
}

async function resetPassword(): Promise<boolean> {
  if (resetForm.new_password.length < 6) {
    Message.warning('新密码至少 6 位')
    return false
  }
  saving.value = true
  try {
    await client.post(`/admin/users/${resetForm.id}/password`, {
      new_password: resetForm.new_password,
    })
    Message.success('密码已重置')
    showReset.value = false
    return true
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '重置密码失败')
    return false
  } finally {
    saving.value = false
  }
}

function delUser(record: any) {
  Modal.confirm({
    title: '删除用户',
    content: `确定删除用户「${record.username}」吗？其简历和面试记录会一并删除，且无法恢复。`,
    okText: '删除',
    okButtonProps: { status: 'danger' },
    onOk: async () => {
      try {
        await client.delete(`/admin/users/${record.id}`)
        Message.success('已删除')
        await loadList()
      } catch (e: any) {
        Message.error(e?.response?.data?.detail || '删除失败')
      }
    },
  })
}

function formatTime(t: string) {
  if (!t) return ''
  const d = new Date(t)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

onMounted(loadList)
</script>

<style scoped>
.card {
  min-height: 200px;
}
</style>
