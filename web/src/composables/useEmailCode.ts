import { onUnmounted, ref } from "vue";
import { api } from "../api/client";
import type { EmailCodePurpose, EmailCodeResponse } from "../types";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function extractErrorMessage(err: unknown, fallback: string): string {
  const e = err as { detail?: { detail?: unknown } | string; message?: string } | null;
  if (!e) return fallback;
  if (typeof e.detail === "string" && e.detail.trim()) return e.detail;
  if (e.detail && typeof e.detail === "object" && typeof e.detail.detail === "string") {
    return e.detail.detail;
  }
  if (typeof e.message === "string" && e.message.trim()) return e.message;
  return fallback;
}

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

export function useEmailCode(purpose: EmailCodePurpose) {
  const sending = ref(false);
  const cooldown = ref(0);
  const notice = ref<string | null>(null);
  let timer: ReturnType<typeof setInterval> | null = null;

  function stopTimer() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  function startCooldown(seconds: number) {
    stopTimer();
    cooldown.value = Math.max(1, Math.round(seconds));
    timer = setInterval(() => {
      if (cooldown.value <= 1) {
        cooldown.value = 0;
        stopTimer();
      } else {
        cooldown.value -= 1;
      }
    }, 1000);
  }

  function clearNotice() {
    notice.value = null;
  }

  async function sendCode(rawEmail: string): Promise<{ ok: boolean; error?: string }> {
    const email = rawEmail.trim();
    if (!email || !isValidEmail(email)) {
      return { ok: false, error: "请输入有效的邮箱地址" };
    }
    if (sending.value || cooldown.value > 0) {
      return { ok: false };
    }
    sending.value = true;
    notice.value = null;
    try {
      const resp = await api.post<EmailCodeResponse>("/auth/email-code", {
        email,
        purpose,
      });
      const ttlMin = Math.max(1, Math.round(resp.expires_in / 60));
      notice.value = `验证码已发送至 ${email}，${ttlMin} 分钟内有效`;
      startCooldown(resp.cooldown);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: extractErrorMessage(e, "验证码发送失败，请稍后重试") };
    } finally {
      sending.value = false;
    }
  }

  onUnmounted(stopTimer);

  return {
    sending,
    cooldown,
    notice,
    sendCode,
    clearNotice,
  };
}
