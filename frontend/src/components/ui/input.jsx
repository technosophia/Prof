import React from 'react'
import { cn } from '@/lib/utils'

export function Input({ className, ...props }) {
  return <input className={cn('w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm', className)} {...props} />
}
