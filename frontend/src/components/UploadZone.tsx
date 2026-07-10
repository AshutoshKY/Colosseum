import { useRef, useState, type DragEvent } from 'react'
import { cx, ErrorBox } from './common'

const MAX_FILES = 50
const MAX_FILE_MB = 300

export function UploadZone({
  onUpload,
  busy,
  accept = '.pdf,application/pdf',
  label = 'Drop PDFs here or choose files',
}: {
  onUpload: (files: File[]) => Promise<unknown> | void
  busy?: boolean
  accept?: string
  label?: string
}) {
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string>()
  const [dragging, setDragging] = useState(false)

  const submit = async (files: File[]) => {
    setError(undefined)
    if (!files.length) return
    if (files.length > MAX_FILES) return setError(`Maximum ${MAX_FILES} files per upload.`)
    if (files.some(file => file.size > MAX_FILE_MB * 1024 * 1024)) return setError(`A file exceeds ${MAX_FILE_MB} MB.`)
    try {
      await onUpload(files)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  const drop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    void submit(Array.from(event.dataTransfer.files))
  }

  return (
    <>
      <button
        type="button"
        className={cx('upload-zone', dragging && 'drag')}
        disabled={busy}
        onClick={() => input.current?.click()}
        onDragOver={event => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        <span>{busy ? 'Uploading…' : label}</span>
        <small>Bulk upload supported · max {MAX_FILES} files / {MAX_FILE_MB} MB</small>
        <input ref={input} hidden type="file" multiple accept={accept} onChange={event => void submit(Array.from(event.target.files ?? []))} />
      </button>
      <ErrorBox error={error} />
    </>
  )
}
