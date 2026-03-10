import React from 'react'

export function Label({ children, ...props }) {
  return (
    <label className="text-sm font-medium text-slate-200" {...props}>
      {children}
    </label>
  )
}
