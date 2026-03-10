import React from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...props }) {
  return <div className={cn('rounded-lg border border-slate-800 bg-slate-900 p-6 shadow', className)} {...props} />
}
