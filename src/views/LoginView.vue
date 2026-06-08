<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const errorMessage = ref('')
const isSubmitting = ref(false)

async function submitLogin() {
  errorMessage.value = ''
  if (!username.value.trim() || !password.value) {
    errorMessage.value = '请输入用户名和密码。'
    return
  }

  isSubmitting.value = true
  try {
    const user = await auth.login(username.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    const target = redirect && redirect.startsWith('/') ? redirect : user.homePath
    await router.replace(target)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录失败，请稍后重试。'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-brand">
        <span class="brand-kicker">Knowledge Graph</span>
        <h1>智能排故知识图谱</h1>
        <p>账号权限决定可访问的业务模块。</p>
      </div>

      <form class="login-form" @submit.prevent="submitLogin">
        <div class="form-heading">
          <h2>账号登录</h2>
          <span>请输入系统账号</span>
        </div>

        <label>
          <span>用户名</span>
          <input
            v-model="username"
            name="username"
            type="text"
            autocomplete="username"
            autofocus
            placeholder="请输入用户名"
          >
        </label>

        <label>
          <span>密码</span>
          <input
            v-model="password"
            name="password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
          >
        </label>

        <p v-if="errorMessage" class="login-error">{{ errorMessage }}</p>

        <button type="submit" :disabled="isSubmitting">
          {{ isSubmitting ? '登录中...' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
:global(body) {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #13253f;
  background: #edf4fb;
}

:global(*) {
  box-sizing: border-box;
}

.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    linear-gradient(rgba(9, 31, 60, 0.72), rgba(9, 31, 60, 0.82)),
    url("/login-bg.png") center / cover no-repeat,
    #0d2949;
}

.login-panel {
  width: min(860px, 100%);
  min-height: 480px;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(340px, 0.9fr);
  overflow: hidden;
  border: 1px solid rgba(213, 229, 248, 0.28);
  border-radius: 8px;
  background: rgba(248, 251, 255, 0.96);
  box-shadow: 0 28px 70px rgba(3, 18, 39, 0.34);
}

.login-brand {
  padding: 58px 48px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  color: #fff;
  background:
    linear-gradient(145deg, rgba(12, 40, 76, 0.96), rgba(20, 83, 137, 0.9)),
    #123c68;
}

.brand-kicker {
  color: #9dc7ff;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.login-brand h1 {
  margin: 14px 0 0;
  font-size: 38px;
  line-height: 1.18;
}

.login-brand p {
  margin: 18px 0 0;
  color: #c9ddf4;
  font-size: 15px;
  line-height: 1.7;
}

.login-form {
  padding: 54px 42px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 20px;
}

.form-heading h2 {
  margin: 0;
  color: #17355e;
  font-size: 28px;
}

.form-heading span {
  display: block;
  margin-top: 7px;
  color: #6c7f9a;
  font-size: 13px;
}

label {
  display: grid;
  gap: 8px;
  color: #314a6b;
  font-size: 13px;
  font-weight: 800;
}

input {
  width: 100%;
  height: 44px;
  border: 1px solid #cddaea;
  border-radius: 6px;
  padding: 0 13px;
  outline: none;
  color: #13253f;
  background: #fff;
  font: inherit;
}

input:focus {
  border-color: #3579db;
  box-shadow: 0 0 0 3px rgba(53, 121, 219, 0.13);
}

.login-error {
  margin: -4px 0 0;
  color: #b4233a;
  font-size: 13px;
  font-weight: 700;
}

button {
  height: 44px;
  border: 0;
  border-radius: 6px;
  color: #fff;
  background: #1f67c7;
  font: inherit;
  font-weight: 900;
  cursor: pointer;
  box-shadow: 0 10px 22px rgba(31, 103, 199, 0.24);
}

button:hover:not(:disabled) {
  background: #1758ad;
}

button:disabled {
  opacity: 0.65;
  cursor: wait;
}

@media (max-width: 720px) {
  .login-panel {
    grid-template-columns: 1fr;
  }

  .login-brand {
    min-height: 190px;
    padding: 32px 28px;
  }

  .login-brand h1 {
    font-size: 30px;
  }

  .login-form {
    padding: 34px 28px 40px;
  }
}
</style>
