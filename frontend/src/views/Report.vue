<template>
  <div class="page">
    <div class="container">
      <a-page-header title="📊 面试复盘报告" @back="goBack" />

      <a-card v-if="loading" :bordered="false">
        <a-spin style="display: block; margin: 60px auto" />
      </a-card>

      <template v-else-if="report">
        <!-- 综合得分 -->
        <a-card class="card">
          <div class="overview">
            <div class="score-box">
              <a-statistic title="综合得分" :value="report.overall_score ?? 0" suffix="分" />
            </div>
            <div class="meta">
              <div>岗位：{{ report.position_name }}</div>
              <div>类型：{{ report.interview_type }} · 共 {{ report.total_rounds }} 轮</div>
              <div>状态：{{ report.status }}</div>
            </div>
          </div>
        </a-card>

        <!-- 能力雷达图 -->
        <a-card v-if="report.skill_scores" title="能力雷达图" class="card">
          <div ref="chartRef" class="chart"></div>
        </a-card>

        <!-- 整体评价与建议 -->
        <a-card v-if="report.feedback_summary" title="整体评价与改进建议" class="card">
          <p class="summary">{{ report.feedback_summary }}</p>
        </a-card>

        <!-- 逐题复盘 -->
        <a-card title="逐题复盘" class="card">
          <a-collapse>
            <a-collapse-item
              v-for="(d, i) in report.details"
              :key="i"
              :header="`Q${d.question_number}（${d.question_type}）${d.question}`"
            >
              <div class="qa">
                <div class="answer"><b>你的回答：</b>{{ d.answer || '（未作答）' }}</div>
                <a-tag color="green" style="margin: 8px 0">得分 {{ d.score ?? '-' }}</a-tag>
                <div v-if="d.strengths?.length"><b>优点：</b>{{ d.strengths.join('；') }}</div>
                <div v-if="d.weaknesses?.length"><b>不足：</b>{{ d.weaknesses.join('；') }}</div>
                <div v-if="d.suggestions?.length"><b>建议：</b>{{ d.suggestions.join('；') }}</div>
                <div v-if="d.model_answer" class="model"><b>参考回答：</b>{{ d.model_answer }}</div>
              </div>
            </a-collapse-item>
          </a-collapse>
        </a-card>
      </template>

      <a-card v-else class="card">
        <a-result status="warning" title="未找到该面试报告" />
      </a-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import client from '../api/client'

const route = useRoute()
const router = useRouter()

const report = ref<any>(null)
const loading = ref(true)
const chartRef = ref<HTMLElement>()

let chart: echarts.ECharts | null = null

const SKILL_LABELS: Record<string, string> = {
  technical_skill: '技术能力',
  communication: '沟通表达',
  problem_solving: '问题解决',
  leadership: '领导力',
  teamwork: '团队协作',
  learning_ability: '学习能力',
  stress_management: '抗压能力',
}

function renderChart(scores: Record<string, number>) {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  const keys = Object.keys(scores).filter((k) => scores[k] != null)
  const indicator = keys.map((k) => ({ name: SKILL_LABELS[k] || k, max: 100 }))
  const value = keys.map((k) => scores[k])
  chart.setOption({
    tooltip: { trigger: 'item' },
    radar: {
      indicator,
      radius: '68%',
      axisName: { color: '#4e5969', fontSize: 13 },
      splitArea: { areaStyle: { color: ['#f7f8fa', '#ffffff'] } },
      splitLine: { lineStyle: { color: '#e5e6eb' } },
      axisLine: { lineStyle: { color: '#e5e6eb' } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value,
            name: '能力评估',
            itemStyle: { color: '#165DFF' },
            lineStyle: { color: '#165DFF', width: 2 },
            areaStyle: { color: 'rgba(22, 93, 255, 0.25)' },
          },
        ],
      },
    ],
  })
}

onMounted(async () => {
  let skillScores: Record<string, number> | null = null
  try {
    const res = await client.get(`/interviews/${route.params.id}/report`)
    report.value = res.data
    skillScores = res.data.skill_scores || null
  } catch (e) {
    report.value = null
  } finally {
    loading.value = false
  }
  // 先关闭 loading 让报告卡片（含雷达图容器）渲染出来，再画图
  if (skillScores) {
    await nextTick()
    renderChart(skillScores)
  }
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

function handleResize() {
  chart?.resize()
}

function goBack() {
  router.push('/')
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24px 16px;
}
.container {
  max-width: 760px;
  margin: 0 auto;
}
.card {
  margin-bottom: 16px;
}
.overview {
  display: flex;
  align-items: center;
  gap: 32px;
}
.score-box {
  min-width: 180px;
}
.meta {
  color: #4e5969;
  line-height: 1.9;
}
.chart {
  width: 100%;
  height: 380px;
}
.summary {
  white-space: pre-wrap;
  line-height: 1.9;
  color: #1d2129;
  margin: 0;
}
.qa {
  color: #4e5969;
  line-height: 1.8;
}
.qa .answer {
  margin-bottom: 8px;
}
.qa .model {
  margin-top: 8px;
  padding: 8px 12px;
  background: #f7f8fa;
  border-radius: 6px;
}
</style>
