import { Button } from '@/components/ui/button'
import { RotateCw, Plus, Minus } from 'lucide-react'

export default function RegenerateButtons({
  onRegenerate,
  onRegenerateWithMore,
  onRegenerateWithLess,
  disabled
}) {
  return (
    <div className="flex items-center justify-center gap-2 py-3 border-t border-slate-800">
      <Button
        variant="outline"
        size="sm"
        onClick={onRegenerateWithLess}
        disabled={disabled}
        className="flex items-center gap-1 text-xs bg-slate-800 hover:bg-slate-700 border-slate-700"
        title="Regenerate with less context (1 chunk)"
      >
        <Minus size={14} />
        <span className="hidden sm:inline">Less context</span>
        <span className="sm:hidden">−</span>
      </Button>

      <Button
        variant="default"
        size="sm"
        onClick={onRegenerate}
        disabled={disabled}
        className="flex items-center gap-1 text-xs bg-blue-600 hover:bg-blue-500"
        title="Regenerate with default context (3 chunks)"
      >
        <RotateCw size={14} />
        <span className="hidden sm:inline">Regenerate</span>
        <span className="sm:hidden">↻</span>
      </Button>

      <Button
        variant="outline"
        size="sm"
        onClick={onRegenerateWithMore}
        disabled={disabled}
        className="flex items-center gap-1 text-xs bg-slate-800 hover:bg-slate-700 border-slate-700"
        title="Regenerate with more context (5 chunks)"
      >
        <Plus size={14} />
        <span className="hidden sm:inline">More context</span>
        <span className="sm:hidden">+</span>
      </Button>
    </div>
  )
}
