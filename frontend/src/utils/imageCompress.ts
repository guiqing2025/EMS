/** 上传前压缩图片（开发占位实现：过大则缩小，否则原样返回） */

export async function compressImageForUpload(
  file: File,
  opts: { maxSide?: number; quality?: number } = {},
): Promise<File> {
  const maxSide = opts.maxSide ?? 1280
  const quality = opts.quality ?? 0.72
  if (!file.type.startsWith('image/')) return file
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') {
    return file
  }

  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
    if (scale >= 1 && file.size < 1.5 * 1024 * 1024) {
      bitmap.close()
      return file
    }
    const w = Math.max(1, Math.round(bitmap.width * scale))
    const h = Math.max(1, Math.round(bitmap.height * scale))
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      bitmap.close()
      return file
    }
    ctx.drawImage(bitmap, 0, 0, w, h)
    bitmap.close()
    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/jpeg', quality),
    )
    if (!blob) return file
    const name = file.name.replace(/\.\w+$/, '') + '.jpg'
    return new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() })
  } catch {
    return file
  }
}
