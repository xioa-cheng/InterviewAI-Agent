<template>
  <div class="landing" ref="root">
    <!-- 顶部导航 -->
    <header class="nav" :class="{ 'nav-scrolled': scrolled }">
      <div class="nav-inner">
        <a class="logo" href="#top" @click.prevent="scrollTo('top')">
          <span class="logo-mark">🎯</span> 面试模拟 Agent
        </a>

        <nav class="nav-links" :class="{ open: mobileOpen }">
          <a href="#features" @click.prevent="scrollTo('features')">功能</a>
          <a href="#demo" @click.prevent="scrollTo('demo')">演示</a>
          <a class="nav-oss" href="https://github.com/xioa-cheng/InterviewAI-Agent" target="_blank" rel="noopener" @click="mobileOpen = false">开源</a>
          <a class="nav-login" href="#top" @click.prevent="goLogin">登录</a>
        </nav>

        <button class="hamburger" @click="mobileOpen = !mobileOpen" aria-label="菜单">
          <span :class="{ x: mobileOpen }"></span>
          <span :class="{ x: mobileOpen }"></span>
          <span :class="{ x: mobileOpen }"></span>
        </button>
      </div>
    </header>

    <!-- Hero -->
    <section class="hero" id="top">
      <div class="hero-grid">
        <div class="hero-copy reveal">
          <span class="badge">基于 LangChain + LangGraph 构建</span>
          <h1 class="hero-title">用 AI 模拟<span class="hl">真实技术面试</span></h1>
          <p class="hero-sub">
            智能面试官、评估官与技能测评，实时流式出题与打分，
            让你在家也能沉浸式备战技术面试。
          </p>
          <div class="hero-actions">
            <button class="btn btn-primary" @click="goStart">免费开始</button>
            <button class="btn btn-ghost" @click="scrollTo('demo')">▶ 观看演示</button>
          </div>
          <div class="hero-trust">
            <span>✓ 按岗位精准出题</span>
            <span>✓ 多维度评分</span>
            <span>✓ 个性化报告</span>
          </div>
        </div>

        <!-- 右侧模拟对话卡片 -->
        <div class="hero-demo reveal" id="demo">
          <div class="mock-chat">
            <div class="chat-head">
              <span class="live-dot"></span> 实时模拟面试 · 进行中
            </div>
            <div class="chat-body">
              <div class="msg interviewer">
                <div class="avatar">面</div>
                <div class="bubble">
                  请实现一个队列，仅使用栈的基本操作（push / pop）。
                </div>
              </div>
              <div class="msg assistant">
                <div class="avatar ai">AI</div>
                <div class="bubble">
                  {{ typed }}<span class="caret" v-if="typing">▋</span>
                </div>
              </div>
            </div>
            <div class="chat-foot">⚡ 流式生成中…</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 功能卡片 -->
    <section class="section" id="features">
      <div class="section-head reveal">
        <h2>核心能力</h2>
        <p>从出题到评估，覆盖一场高质量模拟面试的全流程</p>
      </div>
      <div class="cards">
        <div class="card reveal" v-for="f in features" :key="f.title">
          <div class="card-icon" v-html="f.icon"></div>
          <h3>{{ f.title }}</h3>
          <p>{{ f.desc }}</p>
        </div>
      </div>
    </section>

    <!-- 使用流程 -->
    <section class="section section-alt">
      <div class="section-head reveal">
        <h2>三步开启模拟面试</h2>
        <p>简单直观，几分钟即可拿到专业评估报告</p>
      </div>
      <div class="timeline">
        <div class="step reveal" v-for="(s, i) in steps" :key="s.title">
          <div class="step-num">{{ i + 1 }}</div>
          <div class="step-body">
            <h3>{{ s.title }}</h3>
            <p>{{ s.desc }}</p>
          </div>
          <div class="step-arrow" v-if="i < steps.length - 1">→</div>
        </div>
      </div>
    </section>

    <!-- 开源说明 -->
    <section class="section oss reveal">
      <div class="oss-inner">
        <h2>免费 · 开源</h2>
        <p>本项目面向个人学习与面试备战，完全免费。欢迎到 GitHub 查看源码、提交 Issue 与共建。</p>
        <a class="btn btn-ghost" href="https://github.com/xioa-cheng/InterviewAI-Agent" target="_blank" rel="noopener">前往 GitHub</a>
      </div>
    </section>

    <!-- 底部 CTA -->
    <section class="cta-band reveal">
      <h2>准备好迎接下一场面试了吗？</h2>
      <p>立即免费体验，让 AI 成为你最严苛也最耐心的陪练。</p>
      <button class="btn btn-primary btn-lg" @click="goStart">免费开始模拟面试</button>
    </section>

    <!-- 页脚 -->
    <footer class="footer">
      <div class="footer-inner">
        <div class="footer-brand">🎯 面试模拟 Agent</div>
        <div class="footer-links">
          <a href="#features" @click.prevent="scrollTo('features')">功能</a>
          <a href="#pricing" @click.prevent="scrollTo('pricing')">价格</a>
          <a href="#top" @click.prevent="scrollTo('top')">回到顶部</a>
        </div>
      </div>
      <div class="copyright">© 2026 InterviewAI · 让每一次面试都更有准备</div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../store/user'

const router = useRouter()
const userStore = useUserStore()

const root = ref<HTMLElement | null>(null)
const mobileOpen = ref(false)
const scrolled = ref(false)

// ---- 功能卡片数据 ----
const features = [
  {
    title: '智能出题',
    desc: '基于混合检索（向量 + BM25）的题库，按岗位与难度精准推送题目。',
    icon: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
  },
  {
    title: '实时评估',
    desc: 'ReAct 评估官流式打分，边答边评，即时反馈答题质量。',
    icon: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg>',
  },
  {
    title: '技能测评',
    desc: '多维度能力雷达，从算法、工程到沟通给出结构化成长建议。',
    icon: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 3v9l6 4"/><path d="M12 12l-5 3"/></svg>',
  },
]

// ---- 流程数据 ----
const steps = [
  { title: '选择岗位', desc: '指定目标岗位、级别与技术方向，定制面试剧本。' },
  { title: 'AI 模拟面试', desc: '流式追问、实时应答，沉浸式还原真实面试节奏。' },
  { title: '拿到评估报告', desc: '多维度评分 + 改进建议，清晰看见能力短板。' },
]

// 定价板块已移除：项目定位为免费 / 开源 / 个人学习项目

// ---- 打字机 ----
const answerText =
  '好的，我们用两个栈来实现队列：入队时压入栈 A；出队时若栈 B 为空，先把 A 全部倒入 B，再弹出 B 顶。这样队头总是最先进入的元素，满足 FIFO。'
const typed = ref('')
const typing = ref(true)
let typeTimer: number | undefined

function runTypewriter() {
  let i = 0
  typed.value = ''
  typing.value = true
  const tick = () => {
    if (i <= answerText.length) {
      typed.value = answerText.slice(0, i)
      typing.value = i < answerText.length
      i++
      typeTimer = window.setTimeout(tick, 52)
    } else {
      typing.value = false
      typeTimer = window.setTimeout(() => runTypewriter(), 2800)
    }
  }
  tick()
}

// ---- 滚动入场 ----
let observer: IntersectionObserver | undefined
function setupReveal() {
  if (!root.value) return
  const els = root.value.querySelectorAll('.reveal')
  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          ;(e.target as HTMLElement).classList.add('is-visible')
          observer?.unobserve(e.target)
        }
      })
    },
    { threshold: 0.12 },
  )
  els.forEach((el) => observer?.observe(el))
}

// ---- 滚动监听（导航阴影）----
function onScroll() {
  scrolled.value = window.scrollY > 8
}

// ---- 交互 ----
function scrollTo(id: string) {
  mobileOpen.value = false
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
}
function goLogin() {
  mobileOpen.value = false
  router.push('/login')
}
function goStart() {
  mobileOpen.value = false
  router.push(userStore.isLoggedIn ? '/interview' : '/login')
}

onMounted(() => {
  runTypewriter()
  setupReveal()
  window.addEventListener('scroll', onScroll, { passive: true })
})
onBeforeUnmount(() => {
  if (typeTimer) window.clearTimeout(typeTimer)
  observer?.disconnect()
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.landing {
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: #1e293b;
  background: #ffffff;
}

/* ---------- 导航 ---------- */
.nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid transparent;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.nav-scrolled {
  border-bottom-color: #eef0f4;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04);
}
.nav-inner {
  max-width: 1140px;
  margin: 0 auto;
  height: 64px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 800;
  font-size: 18px;
  color: #1e293b;
  text-decoration: none;
}
.logo-mark {
  font-size: 20px;
}
.nav-links {
  display: flex;
  align-items: center;
  gap: 28px;
}
.nav-links a {
  color: #475569;
  text-decoration: none;
  font-size: 15px;
  font-weight: 500;
  transition: color 0.15s;
}
.nav-links a:hover {
  color: #4f46e5;
}
.nav-login {
  padding: 8px 18px;
  background: #4f46e5;
  color: #fff !important;
  border-radius: 10px;
  font-weight: 600;
}
.nav-login:hover {
  background: #4338ca;
}
.hamburger {
  display: none;
  flex-direction: column;
  gap: 5px;
  width: 40px;
  height: 40px;
  border: none;
  background: transparent;
  cursor: pointer;
  align-items: center;
  justify-content: center;
}
.hamburger span {
  width: 22px;
  height: 2px;
  background: #334155;
  border-radius: 2px;
  transition: transform 0.25s, opacity 0.2s;
}
.hamburger span.x:nth-child(1) {
  transform: translateY(7px) rotate(45deg);
}
.hamburger span.x:nth-child(2) {
  opacity: 0;
}
.hamburger span.x:nth-child(3) {
  transform: translateY(-7px) rotate(-45deg);
}

/* ---------- Hero ---------- */
.hero {
  max-width: 1140px;
  margin: 0 auto;
  padding: 72px 24px 64px;
}
.hero-grid {
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 48px;
  align-items: center;
}
.badge {
  display: inline-block;
  padding: 6px 14px;
  border-radius: 999px;
  background: #eef2ff;
  color: #4f46e5;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 20px;
}
.hero-title {
  font-size: 46px;
  line-height: 1.15;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin: 0 0 18px;
}
.hero-title .hl {
  color: #4f46e5;
}
.hero-sub {
  font-size: 17px;
  line-height: 1.8;
  color: #64748b;
  margin: 0 0 28px;
  max-width: 520px;
}
.hero-actions {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.btn {
  border: none;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  border-radius: 12px;
  padding: 13px 26px;
  transition: transform 0.12s, box-shadow 0.2s, background 0.2s;
  font-family: inherit;
}
.btn:active {
  transform: translateY(1px);
}
.btn-primary {
  background: #4f46e5;
  color: #fff;
  box-shadow: 0 8px 22px rgba(79, 70, 229, 0.3);
}
.btn-primary:hover {
  background: #4338ca;
  box-shadow: 0 10px 28px rgba(79, 70, 229, 0.4);
}
.btn-ghost {
  background: #fff;
  color: #4f46e5;
  border: 1px solid #e0e2ea;
}
.btn-ghost:hover {
  border-color: #4f46e5;
  background: #f5f6ff;
}
.btn-lg {
  padding: 15px 34px;
  font-size: 16px;
}
.hero-trust {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 26px;
  color: #64748b;
  font-size: 14px;
}

/* ---------- 模拟对话卡片 ---------- */
.mock-chat {
  background: #fff;
  border: 1px solid #eef0f4;
  border-radius: 18px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.1);
  overflow: hidden;
}
.chat-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  background: #f8fafc;
  border-bottom: 1px solid #eef0f4;
  font-size: 13px;
  color: #64748b;
  font-weight: 600;
}
.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.18);
}
.chat-body {
  padding: 20px 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 200px;
}
.msg {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.avatar {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  background: #e2e8f0;
  color: #475569;
}
.avatar.ai {
  background: #4f46e5;
  color: #fff;
}
.bubble {
  background: #f1f5f9;
  border-radius: 12px;
  padding: 11px 14px;
  font-size: 14px;
  line-height: 1.7;
  color: #334155;
  max-width: 100%;
}
.msg.assistant .bubble {
  background: #eef2ff;
  color: #312e81;
}
.caret {
  display: inline-block;
  margin-left: 1px;
  color: #4f46e5;
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.chat-foot {
  padding: 12px 18px;
  border-top: 1px solid #eef0f4;
  font-size: 12px;
  color: #94a3b8;
}

/* ---------- 通用 section ---------- */
.section {
  max-width: 1140px;
  margin: 0 auto;
  padding: 72px 24px;
}
.section-alt {
  max-width: none;
  background: #f8fafc;
}
.section-alt > * {
  max-width: 1140px;
  margin-left: auto;
  margin-right: auto;
}
.section-head {
  text-align: center;
  margin-bottom: 44px;
}
.section-head h2 {
  font-size: 32px;
  font-weight: 800;
  margin: 0 0 10px;
  letter-spacing: -0.01em;
}
.section-head p {
  color: #64748b;
  font-size: 16px;
  margin: 0;
}

/* ---------- 功能卡片 ---------- */
.cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 22px;
}
.card {
  background: #fff;
  border: 1px solid #eef0f4;
  border-radius: 18px;
  padding: 28px 24px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition: transform 0.18s, box-shadow 0.2s, border-color 0.2s;
}
.card:hover {
  transform: translateY(-6px);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.1);
  border-color: #e0e7ff;
}
.card-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: #eef2ff;
  color: #4f46e5;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 18px;
  transition: transform 0.18s;
}
.card:hover .card-icon {
  transform: scale(1.05);
}
.card h3 {
  font-size: 19px;
  font-weight: 700;
  margin: 0 0 8px;
}
.card p {
  color: #64748b;
  font-size: 14.5px;
  line-height: 1.7;
  margin: 0;
}

/* ---------- 流程时间线 ---------- */
.timeline {
  display: flex;
  align-items: stretch;
  gap: 12px;
}
.step {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border: 1px solid #eef0f4;
  border-radius: 16px;
  padding: 22px;
  position: relative;
}
.step-num {
  flex: 0 0 auto;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: #4f46e5;
  color: #fff;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.step-body h3 {
  font-size: 17px;
  margin: 0 0 6px;
}
.step-body p {
  color: #64748b;
  font-size: 14px;
  line-height: 1.6;
  margin: 0;
}
.step-arrow {
  position: absolute;
  right: -16px;
  top: 50%;
  transform: translateY(-50%);
  color: #cbd5e1;
  font-size: 20px;
  z-index: 2;
}

/* ---------- 开源说明 ---------- */
.oss {
  text-align: center;
}
.oss-inner {
  max-width: 640px;
  margin: 0 auto;
  background: #f8fafc;
  border: 1px solid #eef0f4;
  border-radius: 18px;
  padding: 40px 28px;
}
.oss h2 {
  font-size: 26px;
  font-weight: 800;
  margin: 0 0 12px;
}
.oss p {
  color: #64748b;
  font-size: 15px;
  line-height: 1.7;
  margin: 0 0 22px;
}

/* ---------- CTA ---------- */
.cta-band {
  max-width: 1140px;
  margin: 0 auto 72px;
  padding: 56px 24px;
  text-align: center;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 60%, #818cf8 100%);
  border-radius: 24px;
  color: #fff;
}
.cta-band h2 {
  font-size: 30px;
  font-weight: 800;
  margin: 0 0 10px;
}
.cta-band p {
  font-size: 16px;
  opacity: 0.92;
  margin: 0 0 26px;
}

/* ---------- 页脚 ---------- */
.footer {
  border-top: 1px solid #eef0f4;
  padding: 40px 24px 28px;
}
.footer-inner {
  max-width: 1140px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}
.footer-brand {
  font-weight: 700;
  font-size: 16px;
}
.footer-links {
  display: flex;
  gap: 22px;
}
.footer-links a {
  color: #64748b;
  text-decoration: none;
  font-size: 14px;
}
.footer-links a:hover {
  color: #4f46e5;
}
.copyright {
  max-width: 1140px;
  margin: 20px auto 0;
  color: #94a3b8;
  font-size: 13px;
}

/* ---------- 滚动入场动画 ---------- */
.reveal {
  opacity: 0;
  transform: translateY(24px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}
.reveal.is-visible {
  opacity: 1;
  transform: none;
}

/* ---------- 响应式 ---------- */
@media (max-width: 768px) {
  .hamburger {
    display: flex;
  }
  .nav-links {
    position: absolute;
    top: 64px;
    left: 0;
    right: 0;
    flex-direction: column;
    align-items: stretch;
    gap: 0;
    background: #fff;
    border-bottom: 1px solid #eef0f4;
    padding: 8px 24px 16px;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
    display: none;
  }
  .nav-links.open {
    display: flex;
  }
  .nav-links a {
    padding: 12px 0;
    border-bottom: 1px solid #f1f5f9;
  }
  .nav-login {
    text-align: center;
    margin-top: 8px;
    border-radius: 10px;
  }
  .hero {
    padding: 48px 20px 40px;
  }
  .hero-grid {
    grid-template-columns: 1fr;
    gap: 36px;
  }
  .hero-title {
    font-size: 34px;
  }
  .cards {
    grid-template-columns: 1fr;
  }
  .timeline {
    flex-direction: column;
  }
  .step-arrow {
    display: none;
  }
  .section {
    padding: 56px 20px;
  }
}
</style>
