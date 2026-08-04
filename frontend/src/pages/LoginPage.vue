<script setup lang="ts">
/**
 * 로그인 / 초대코드 가입 (CONTRACT §5.1).
 *
 * 서버 에러(`detail`)는 카드 안 인라인 알림으로 보여준다 — 폼 화면에서는
 * 스낵바보다 인라인이 눈에 잘 띈다.
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { errorMessage } from '@/api/endpoints'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const auth = useAuthStore()

const tab = ref<'login' | 'register'>('login')
const loading = ref(false)
const error = ref('')
const showPassword = ref(false)

// 로그인 폼
const loginEmail = ref('')
const loginPassword = ref('')

// 가입 폼
const regEmail = ref('')
const regName = ref('')
const regPassword = ref('')
const regPasswordConfirm = ref('')
const regInviteCode = ref('')

/** `?redirect=` 는 내부 경로만 허용한다 (외부 리다이렉트 방지). */
const redirectTo = computed(() => {
  const raw = route.query.redirect
  const path = typeof raw === 'string' ? raw : ''
  if (!path.startsWith('/') || path.startsWith('//') || path.startsWith('/login')) return '/'
  return path
})

watch(tab, () => {
  error.value = ''
})

async function onLogin(): Promise<void> {
  error.value = ''
  const email = loginEmail.value.trim()
  if (!email || !loginPassword.value) {
    error.value = '이메일과 비밀번호를 입력해 주세요.'
    return
  }

  loading.value = true
  try {
    await auth.login(email, loginPassword.value)
    appStore.toast(`${auth.user?.name ?? ''}님, 환영합니다.`, 'success')
    await router.replace(redirectTo.value)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function onRegister(): Promise<void> {
  error.value = ''
  const email = regEmail.value.trim()
  const name = regName.value.trim()

  if (!email || !name || !regPassword.value || !regInviteCode.value.trim()) {
    error.value = '모든 항목을 입력해 주세요.'
    return
  }
  if (regPassword.value.length < 8) {
    error.value = '비밀번호는 최소 8자 이상이어야 합니다.'
    return
  }
  if (regPassword.value !== regPasswordConfirm.value) {
    error.value = '비밀번호가 서로 다릅니다.'
    return
  }

  loading.value = true
  try {
    await auth.register({
      email,
      name,
      password: regPassword.value,
      invite_code: regInviteCode.value.trim(),
    })
    appStore.toast(
      auth.isAdmin ? '가입 완료 — 첫 계정이라 관리자로 등록되었습니다.' : '가입이 완료되었습니다.',
      'success',
    )
    await router.replace(redirectTo.value)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <v-container class="fill-height pa-4" style="max-width: 480px">
    <div class="w-100">
      <div class="text-center mb-6">
        <v-icon icon="mdi-wallet-outline" size="44" color="primary" />
        <h1 class="text-h5 font-weight-bold mt-2">연구실 선결제 관리</h1>
        <p class="text-body-2 text-medium-emphasis mt-1">식당 선결제 잔액을 함께 기록합니다.</p>
      </div>

      <v-card>
        <v-tabs v-model="tab" grow color="primary">
          <v-tab value="login">로그인</v-tab>
          <v-tab value="register">가입</v-tab>
        </v-tabs>

        <v-divider />

        <v-card-text class="pt-5">
          <v-alert v-if="error" type="error" density="comfortable" class="mb-4">
            {{ error }}
          </v-alert>

          <v-window v-model="tab">
            <!-- ── 로그인 ── -->
            <v-window-item value="login">
              <v-form @submit.prevent="onLogin">
                <v-text-field
                  v-model="loginEmail"
                  label="이메일"
                  type="email"
                  autocomplete="email"
                  inputmode="email"
                  prepend-inner-icon="mdi-email-outline"
                  autofocus
                  class="mb-3"
                />
                <v-text-field
                  v-model="loginPassword"
                  label="비밀번호"
                  :type="showPassword ? 'text' : 'password'"
                  autocomplete="current-password"
                  prepend-inner-icon="mdi-lock-outline"
                  :append-inner-icon="showPassword ? 'mdi-eye-off' : 'mdi-eye'"
                  class="mb-4"
                  @click:append-inner="showPassword = !showPassword"
                />
                <v-btn type="submit" color="primary" size="large" block :loading="loading">
                  로그인
                </v-btn>
              </v-form>
            </v-window-item>

            <!-- ── 가입 ── -->
            <v-window-item value="register">
              <v-form @submit.prevent="onRegister">
                <v-text-field
                  v-model="regEmail"
                  label="이메일"
                  type="email"
                  autocomplete="email"
                  inputmode="email"
                  prepend-inner-icon="mdi-email-outline"
                  class="mb-3"
                />
                <v-text-field
                  v-model="regName"
                  label="이름"
                  autocomplete="name"
                  prepend-inner-icon="mdi-account-outline"
                  class="mb-3"
                />
                <v-text-field
                  v-model="regPassword"
                  label="비밀번호"
                  :type="showPassword ? 'text' : 'password'"
                  autocomplete="new-password"
                  prepend-inner-icon="mdi-lock-outline"
                  :append-inner-icon="showPassword ? 'mdi-eye-off' : 'mdi-eye'"
                  hint="최소 8자"
                  persistent-hint
                  class="mb-3"
                  @click:append-inner="showPassword = !showPassword"
                />
                <v-text-field
                  v-model="regPasswordConfirm"
                  label="비밀번호 확인"
                  :type="showPassword ? 'text' : 'password'"
                  autocomplete="new-password"
                  prepend-inner-icon="mdi-lock-check-outline"
                  :error="!!regPasswordConfirm && regPassword !== regPasswordConfirm"
                  :error-messages="
                    !!regPasswordConfirm && regPassword !== regPasswordConfirm
                      ? '비밀번호가 서로 다릅니다.'
                      : ''
                  "
                  class="mb-3"
                />
                <v-text-field
                  v-model="regInviteCode"
                  label="초대코드"
                  autocomplete="off"
                  prepend-inner-icon="mdi-key-outline"
                  hint="연구실 관리자에게 받은 초대코드를 입력하세요"
                  persistent-hint
                  class="mb-4"
                />
                <v-btn type="submit" color="primary" size="large" block :loading="loading">
                  가입하기
                </v-btn>
              </v-form>
            </v-window-item>
          </v-window>
        </v-card-text>
      </v-card>

      <v-alert
        v-if="tab === 'register'"
        type="info"
        density="comfortable"
        class="mt-4 text-body-2"
        icon="mdi-information-outline"
      >
        가장 처음 가입한 계정은 자동으로 <strong>관리자</strong>가 됩니다. 이후 가입자는 일반
        구성원이며, 초대코드는 관리자 화면에서 확인할 수 있습니다.
      </v-alert>
    </div>
  </v-container>
</template>
