<template>
  <div class="page">
    <div class="container">
      <h1 class="title">🎯 InterviewAI · AI 面试模拟</h1>

      <!-- 配置阶段 -->
      <a-card v-if="phase === 'setup'" class="card">
        <template #title>开始一场模拟面试</template>
        <a-form :model="config" layout="vertical" @submit="start">
          <a-form-item label="应聘岗位">
            <a-input v-model="config.position_name" placeholder="例如：后端开发工程师" />
          </a-form-item>
          <a-form-item label="简历（可选，用于定制出题）">
            <a-select v-model="config.resume_id" placeholder="选择简历，不选则用最新简历" allow-clear>
              <a-option v-for="r in resumes" :key="r.id" :value="r.id">{{ r.title }}</a-option>
            </a-select>
          </a-form-item>
          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="面试类型">
                <a-select v-model="config.interview_type">
                  <a-option value="mixed">综合</a-option>
                  <a-option value="technical">技术</a-option>
                  <a-option value="behavioral">行为</a-option>
                  <a-option value="project">项目</a-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="难度">
                <a-select v-model="config.difficulty_level">
                  <a-option value="easy">简单</a-option>
                  <a-option value="medium">中等</a-option>
                  <a-option value="hard">困难</a-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="轮数">
                <a-input-number v-model="config.total_rounds" :min="1" :max="10" />
              </a-form-item>
            </a-col>
          </a-row>
          <a-button type="primary" html-type="submit" :loading="loading" long>
            开始面试
          </a-button>
        </a-form>
      </a-card>

      <!-- 面试进行阶段 -->
      <template v-else-if="phase === 'session'">
        <a-card class="card">
          <div class="round-bar">
            <a-tag color="arcoblue">第 {{ currentRound }} / {{ totalRounds }} 轮</a-tag>
            <a-tag>{{ questionType }}</a-tag>
            <a-button size="mini" @click="speak(question)">🔊 朗读题目</a-button>
          </div>
          <div class="question">{{ question }}</div>
          <a-textarea
            v-model="answer"
            :auto-size="{ minRows: 5, maxRows: 12 }"
            placeholder="在此输入你的回答…（也可点下方「语音输入」直接说话）"
            :disabled="loading"
          />
          <div class="actions">
            <a-button type="primary" :loading="loading" @click="submit">提交回答</a-button>
            <a-button :loading="listening" @click="listen">🎤 语音输入</a-button>
            <a-button @click="reset">重新开始</a-button>
          </div>
        </a-card>

        <!-- 评估结果 -->
        <a-card v-if="evaluation" class="card eval">
          <template #title>
            本轮评估
            <a-tag color="green" size="large" style="margin-left: 8px">{{ evaluation.score }} 分</a-tag>
          </template>
          <a-descriptions :column="1" bordered size="small">
            <a-descriptions-item label="优点">
              <div v-for="(s, i) in evaluation.strengths" :key="i">· {{ s }}</div>
            </a-descriptions-item>
            <a-descriptions-item label="不足">
              <div v-for="(s, i) in evaluation.weaknesses" :key="i">· {{ s }}</div>
            </a-descriptions-item>
            <a-descriptions-item label="建议">
              <div v-for="(s, i) in evaluation.suggestions" :key="i">· {{ s }}</div>
            </a-descriptions-item>
            <a-descriptions-item label="参考回答">{{ evaluation.model_answer }}</a-descriptions-item>
          </a-descriptions>
        </a-card>
      </template>

      <!-- 完成阶段 -->
      <a-card v-else class="card">
        <a-result status="success" title="面试完成！">
          <template #subtitle>
            <div v-if="report" class="report">
              <a-statistic title="综合得分" :value="report.overall_score ?? '-'" suffix="分" />
              <p style="margin-top: 12px">岗位：{{ report.position_name }} · 类型：{{ report.interview_type }}</p>
            </div>
          </template>
          <template #extra>
            <a-button type="primary" @click="reset">再来一场</a-button>
          </template>
        </a-result>

        <a-divider v-if="report && report.details.length">逐题回顾</a-divider>
        <div v-for="(d, i) in (report?.details ?? [])" :key="i" class="qa-item">
          <div class="q">Q{{ d.question_number }}（{{ d.question_type }}）：{{ d.question }}</div>
          <div class="a">你的回答：{{ d.answer }}</div>
          <a-tag color="green">得分 {{ d.score ?? '-' }}</a-tag>
          <div v-if="d.suggestions?.length" class="a">建议：{{ d.suggestions.join('；') }}</div>
        </div>
      </a-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import client from '../api/client'

const router = useRouter()
const route = useRoute()

type Phase = 'setup' | 'session' | 'done'

const phase = ref<Phase>('setup')
const loading = ref(false)
const config = reactive({
  position_name: '后端开发工程师',
  interview_type: 'mixed',
  difficulty_level: 'medium',
  total_rounds: 5,
  resume_id: null as string | null,
})

const resumes = ref<any[]>([])

async function loadResumes() {
  try {
    const res = await client.get('/resumes')
    resumes.value = res.data
    const qid = route.query.resume_id as string
    if (qid) {
      config.resume_id = qid
    } else if (res.data.length) {
      config.resume_id = res.data[0].id
    }
  } catch (e) {
    resumes.value = []
  }
}

const interviewId = ref('')
const question = ref('')
const questionType = ref('')
const currentRound = ref(1)
const totalRounds = ref(5)
const answer = ref('')
const evaluation = ref<any>(null)
const report = ref<any>(null)
const listening = ref(false)

async function start() {
  loading.value = true
  try {
    const res = await client.post('/interviews/start', { ...config })
    interviewId.value = res.data.interview_id
    question.value = res.data.question
    questionType.value = res.data.question_type
    currentRound.value = res.data.current_round
    totalRounds.value = res.data.total_rounds
    answer.value = ''
    evaluation.value = null
    report.value = null
    phase.value = 'session'
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '开始面试失败')
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!answer.value.trim()) {
    Message.warning('请先输入回答')
    return
  }
  loading.value = true
  try {
    const res = await client.post(`/interviews/${interviewId.value}/answer`, { answer: answer.value })
    evaluation.value = res.data.evaluation
    if (res.data.completed) {
      Message.success('面试完成，正在生成能力报告…')
      router.push(`/report/${interviewId.value}`)
    } else {
      question.value = res.data.next_question
      currentRound.value = res.data.current_round
      answer.value = ''
      Message.success('已进入下一题')
    }
  } catch (e: any) {
    Message.error(e?.response?.data?.detail || '提交失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  phase.value = 'setup'
  answer.value = ''
  evaluation.value = null
  report.value = null
}

onMounted(loadResumes)

function speak(text: string) {
  if (!('speechSynthesis' in window)) {
    Message.warning('当前浏览器不支持语音合成')
    return
  }
  const utter = new SpeechSynthesisUtterance(text)
  utter.lang = 'zh-CN'
  utter.rate = 1
  speechSynthesis.cancel()
  speechSynthesis.speak(utter)
}

function listen() {
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SR) {
    Message.warning('当前浏览器不支持语音识别（建议用 Edge / Chrome）')
    return
  }
  const rec = new SR()
  rec.lang = 'zh-CN'
  rec.interimResults = false
  rec.onresult = (e: any) => {
    const text = e.results[0][0].transcript
    answer.value = answer.value ? answer.value + text : text
  }
  rec.onerror = (e: any) => {
    Message.error('语音识别失败：' + (e?.error || '未知错误'))
  }
  rec.onend = () => {
    listening.value = false
  }
  listening.value = true
  rec.start()
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 40px 16px;
}
.container {
  max-width: 760px;
  margin: 0 auto;
}
.title {
  text-align: center;
  margin-bottom: 24px;
  color: #1d2129;
}
.card {
  margin-bottom: 16px;
}
.round-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.question {
  font-size: 18px;
  font-weight: 600;
  color: #1d2129;
  margin-bottom: 16px;
  line-height: 1.6;
}
.actions {
  margin-top: 16px;
  display: flex;
  gap: 12px;
}
.eval {
  border-left: 4px solid #00b42a;
}
.report {
  text-align: center;
}
.qa-item {
  margin-bottom: 16px;
  padding: 12px;
  background: #f7f8fa;
  border-radius: 8px;
}
.qa-item .q {
  font-weight: 600;
  margin-bottom: 6px;
}
.qa-item .a {
  color: #4e5969;
  margin-bottom: 6px;
}
</style>
