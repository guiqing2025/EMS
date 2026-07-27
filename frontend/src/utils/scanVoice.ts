/** 工序/包装扫码女声提示：成功 PASS，失败 FALL */

const PASS_URL = '/static/sounds/pass.wav'
const FALL_URL = '/static/sounds/fall.wav'

let passAudio: HTMLAudioElement | null = null
let fallAudio: HTMLAudioElement | null = null
let unlocked = false

function ensureAudio() {
  if (!passAudio) {
    passAudio = new Audio(PASS_URL)
    passAudio.preload = 'auto'
  }
  if (!fallAudio) {
    fallAudio = new Audio(FALL_URL)
    fallAudio.preload = 'auto'
  }
}

/** 弹窗打开时预加载，并尝试解锁自动播放策略 */
export function preloadScanVoice() {
  ensureAudio()
  try {
    passAudio!.load()
    fallAudio!.load()
  } catch {
    /* ignore */
  }
}

async function playEl(el: HTMLAudioElement) {
  try {
    el.pause()
    el.currentTime = 0
    await el.play()
    unlocked = true
  } catch {
    // 自动播放被拦时：克隆再试一次；仍失败则静默（用户已操作过一般可播）
    try {
      const clone = el.cloneNode(true) as HTMLAudioElement
      clone.volume = 1
      await clone.play()
      unlocked = true
    } catch {
      /* ignore */
    }
  }
}

export function playScanPass() {
  ensureAudio()
  void playEl(passAudio!)
}

export function playScanFall() {
  ensureAudio()
  void playEl(fallAudio!)
}

export function playScanResult(ok: boolean) {
  if (ok) playScanPass()
  else playScanFall()
}

/** 供调试：是否已成功播过 */
export function isScanVoiceUnlocked() {
  return unlocked
}
