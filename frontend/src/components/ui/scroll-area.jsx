import { cn } from '@/lib/utils'

export function ScrollArea({ className, children }) {
  return <div className={cn('overflow-y-auto', className)}>{children}</div>
}
