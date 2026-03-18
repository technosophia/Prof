import { RotateCw, Plus, Minus } from 'lucide-react'

export default function RegenerateButtons({
  onRegenerate,
  onRegenerateWithMore,
  onRegenerateWithLess,
  disabled
}) {
  return (
    <div className="flex items-center justify-center gap-1 py-2 px-3">
      <button
        onClick={onRegenerateWithLess}
        disabled={disabled}
        className="p-1.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title="Regenerate with less context (1 chunk)"
      >
        <Minus size={16} />
      </button>

      <button
        onClick={onRegenerate}
        disabled={disabled}
        className="p-1.5 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1"
        title="Regenerate with default context (3 chunks)"
      >
        <RotateCw size={16} />
        <span className="text-xs">Regenerate</span>
      </button>

      <button
        onClick={onRegenerateWithMore}
        disabled={disabled}
        className="p-1.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        title="Regenerate with more context (5 chunks)"
      >
        <Plus size={16} />
      </button>
    </div>
  )
}
