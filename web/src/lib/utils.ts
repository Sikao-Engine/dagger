import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '\u2014'
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  return `${Math.floor(seconds / 60)}m ${(seconds % 60).toFixed(0)}s`
}

export function formatDatetime(iso: string | null | undefined): string {
  if (!iso) return '\u2014'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '\u2014'
  return d.toLocaleString()
}

export function truncate(s: string, n: number): string {
  if (s.length <= n) return s
  return s.slice(0, n - 1) + '\u2026'
}
