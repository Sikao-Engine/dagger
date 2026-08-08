import { useParams, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@ui/button'
import { Badge } from '@ui/badge'
import { useAttemptStream, type TranscriptMessage } from '@sdk/sse'
import { cn } from '@lib/utils'

function MessageView({ msg }: { msg: TranscriptMessage }) {
  return (
    <div className="border-b border-slate-800 last:border-b-0 py-2">
      <div className="text-xs text-slate-500 mb-1">
        <span className="font-mono">{msg.info.role}</span>
        {msg.info.agent && <span className="ml-2 text-blue-400">{msg.info.agent}</span>}
      </div>
      <div className="space-y-1">
        {msg.parts.map((part, i) => {
          switch (part.type) {
            case 'text':
              return (
                <div key={i} className="text-sm text-slate-200 whitespace-pre-wrap">
                  {part.text}
                </div>
              )
            case 'reasoning':
              return (
                <div key={i} className="text-xs text-slate-500 italic whitespace-pre-wrap pl-2 border-l-2 border-slate-700">
                  {part.text}
                </div>
              )
            case 'tool':
              return (
                <div key={i} className="text-xs bg-slate-800/50 rounded p-2 font-mono">
                  <div className="text-blue-300">
                    {part.tool}
                    {part.state?.status && (
                      <span className="ml-2 text-slate-400">[{part.state.status}]</span>
                    )}
                  </div>
                  {part.state?.input != null && (
                    <pre className="text-slate-400 mt-1 overflow-auto max-h-40">
                      {typeof part.state.input === 'string'
                        ? part.state.input
                        : JSON.stringify(part.state.input, null, 2)}
                    </pre>
                  )}
                  {part.state?.output != null && (
                    <pre className="text-emerald-300/70 mt-1 overflow-auto max-h-40">
                      {typeof part.state.output === 'string'
                        ? part.state.output
                        : JSON.stringify(part.state.output, null, 2)}
                    </pre>
                  )}
                </div>
              )
            case 'step-start':
              return (
                <div key={i} className="text-[10px] text-slate-600 border-t border-slate-800 pt-1">
                  ── step ──
                </div>
              )
            case 'step-finish':
              return (
                <div key={i} className="text-[10px] text-slate-600 pb-1">
                  ── end ──
                </div>
              )
            default:
              return null
          }
        })}
      </div>
    </div>
  )
}

export default function AttemptDetailPage() {
  const { attemptId = '' } = useParams<{ attemptId: string }>()
  const { messages, connected, finished, error, historyLoaded } = useAttemptStream(attemptId)

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 p-3 border-b border-slate-800 bg-slate-900">
        <Link to="..">
          <Button variant="ghost" size="icon">
            <ArrowLeft size={16} />
          </Button>
        </Link>
        <h1 className="font-mono text-sm flex-1">{attemptId}</h1>
        {historyLoaded && <Badge variant="secondary">history</Badge>}
        {connected && <Badge>live</Badge>}
        {finished && <Badge variant="outline">done</Badge>}
      </div>

      {error && <div className="px-3 py-1 text-xs text-red-400 bg-red-950/30">{error}</div>}

      <div className="flex-1 overflow-y-auto p-4 bg-slate-950">
        {messages.length === 0 && !historyLoaded ? (
          <div className="text-center text-slate-500 text-sm py-8">加载 transcript...</div>
        ) : messages.length === 0 ? (
          <div className="text-center text-slate-500 text-sm py-8">无消息</div>
        ) : (
          <div className={cn('max-w-4xl mx-auto')}>
            {messages.map((m, i) => (
              <MessageView key={i} msg={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
