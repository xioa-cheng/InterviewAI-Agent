<template>
  <div>
    <a-page-header title="📄 简历管理" subtitle="上传简历后，面试题目将根据你的经历定制" />

    <a-row :gutter="16">
      <!-- 简历列表 -->
      <a-col :span="14">
        <a-card title="我的简历" class="card">
          <a-empty v-if="!resumes.length" description="暂无简历，请在右侧添加" />
          <div v-else>
            <a-card v-for="r in resumes" :key="r.id" class="resume-item" :bordered="true">
              <div class="resume-head">
                <div class="title">{{ r.title }}</div>
                <div class="time">{{ formatTime(r.created_at) }}</div>
              </div>
              <div class="preview">{{ r.content?.slice(0, 120) }}{{ r.content?.length > 120 ? '…' : '' }}</div>
              <div class="resume-actions">
                <a-button type="primary" size="small" @click="startWithResume(r.id)">用此简历面试</a-button>
                <a-button size="small" status="danger" @click="delResume(r.id)">删除</a-button>
              </div>
            </a-card>
          </div>
        </a-card>
      </a-col>

      <!-- 新增简历 -->
      <a-col :span="10">
        <a-card title="新增简历" class="card">
          <a-form :model="form" layout="vertical">
            <a-form-item label="简历标题">
              <a-input v-model="form.title" placeholder="例如：后端开发工程师简历" />
            </a-form-item>
            <a-form-item label="简历内容">
              <a-textarea
                v-model="form.content"
                :auto-size="{ minRows: 8, maxRows: 16 }"
                placeholder="粘贴你的简历文本：个人简介、技能、项目经历、工作经历…"
              />
            </a-form-item>
            <a-upload :show-file-list="false" :auto-upload="false" accept=".txt,.md,.pdf,.docx,.jpg,.jpeg,.png,.bmp,.webp" @change="onFileChange">
              <a-button :loading="uploading">📎 上传文件（docx / pdf / 图片 / txt）</a-button>
            </a-upload>
            <a-button type="primary" long :loading="saving" style="margin-top: 16px" @click="save">
              保存简历
            </a-button>
          </a-form>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Message, Modal } from '@arco-design/web-vue'
import client from '../api/client'

const router = useRouter()

const resumes = ref<any[]>([])
const saving = ref(false)
const uploading = ref(false)
const form = reactive({ title: '', content: '' })
const uploadedFiles = new Set<File>()

async function loadResumes() {
  try {
    const res = await client.get('/resumes')
    resumes.value = res.data
  } catch (e) {
    resumes.value = []
  }
}

async function onFileChange(_fileList: any[], file: any) {
  const raw = file?.file ?? file?.originFile ?? file
  if (!raw) return
  // 同一文件可能触发多次 change（加入列表/上传状态变化），去重避免重复上传
  if (uploadedFiles.has(raw)) return
  uploadedFiles.add(raw)
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', raw)
    fd.append('title', form.title || '')
    const res = await client.post('/resumes/upload', fd)
    Message.success(`已解析「${res.data.title}」并创建简历`)
    form.title = res.data.title || form.title
    form.content = res.data.content || ''
    await loadResumes()
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '上传解析失败')
  } finally {
    uploading.value = false
  }
}

async function save() {
  if (!form.title.trim() || !form.content.trim()) {
    Message.warning('请填写标题和内容')
    return
  }
  saving.value = true
  try {
    await client.post('/resumes', { title: form.title, content: form.content })
    Message.success('简历已保存')
    form.title = ''
    form.content = ''
    await loadResumes()
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function startWithResume(id: string) {
  router.push({ path: '/', query: { resume_id: id } })
}

function delResume(id: string) {
  Modal.confirm({
    title: '删除简历',
    content: '确定删除这份简历吗？删除后无法恢复。',
    okText: '删除',
    okButtonProps: { status: 'danger' },
    onOk: async () => {
      try {
        await client.delete(`/resumes/${id}`)
        Message.success('已删除')
        await loadResumes()
      } catch (e: any) {
        Message.error(e?.response?.data?.detail || '删除失败')
      }
    },
  })
}

function formatTime(t: string) {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(loadResumes)
</script>

<style scoped>
.card {
  height: 100%;
}
.resume-item {
  margin-bottom: 12px;
}
.resume-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.resume-head .title {
  font-weight: 600;
  color: #1d2129;
}
.resume-head .time {
  color: #86909c;
  font-size: 12px;
}
.preview {
  color: #4e5969;
  font-size: 13px;
  line-height: 1.7;
  margin-bottom: 12px;
  word-break: break-all;
}
.resume-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
