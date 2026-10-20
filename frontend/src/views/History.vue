<template>
  <div>
    <a-page-header title="📊 面试历史" subtitle="回看每一次模拟面试与报告">
      <template #extra>
        <a-button :loading="loading" @click="loadList">刷新</a-button>
      </template>
    </a-page-header>

    <a-card class="card">
      <a-spin :loading="loading">
        <a-empty v-if="!loading && !list.length" description="还没有面试记录，去「面试模拟」开始一场吧" />
        <a-table v-else :data="list" :columns="columns" :pagination="false" row-key="interview_id" />
      </a-spin>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Message, Modal, Tag } from '@arco-design/web-vue'
import client from '../api/client'

const router = useRouter()
const list = ref<any[]>([])
const loading = ref(false)

const columns = [
  { title: '岗位', dataIndex: 'position_name' },
  { title: '类型', dataIndex: 'interview_type', width: 90 },
  {
    title: '得分',
    width: 90,
    render: ({ record }: any) => {
      const s = record.overall_score
      const color = s == null ? 'gray' : s >= 80 ? 'green' : s >= 60 ? 'orange' : 'red'
      return h(Tag, { color }, () => (s == null ? '-' : String(s)))
    },
  },
  {
    title: '状态',
    width: 100,
    render: ({ record }: any) =>
      record.status === 'completed'
        ? h(Tag, { color: 'green' }, () => '已完成')
        : h(Tag, { color: 'arcoblue' }, () => '进行中'),
  },
  {
    title: '时间',
    width: 180,
    render: ({ record }: any) => formatTime(record.started_at),
  },
  {
    title: '操作',
    width: 160,
    render: ({ record }: any) =>
      h('span', [
        h(
          Button,
          { type: 'text', size: 'small', onClick: () => view(record.interview_id) },
          () => (record.status === 'completed' ? '查看报告' : '查看'),
        ),
        h(
          Button,
          { type: 'text', size: 'small', status: 'danger', onClick: () => del(record.interview_id) },
          () => '删除',
        ),
      ]),
  },
]

async function loadList() {
  loading.value = true
  try {
    const res = await client.get('/interviews')
    list.value = res.data
  } catch (e: any) {
    list.value = []
    Message.error(e?.response?.data?.detail || '加载历史记录失败')
  } finally {
    loading.value = false
  }
}

function view(id: string) {
  router.push(`/report/${id}`)
}

function del(id: string) {
  Modal.confirm({
    title: '删除面试记录',
    content: '确定删除这条面试记录吗？删除后无法恢复。',
    okText: '删除',
    okButtonProps: { status: 'danger' },
    onOk: async () => {
      try {
        await client.delete(`/interviews/${id}`)
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
