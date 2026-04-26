import React, { useEffect, useMemo, useState } from 'react'
import { Bot, Clock, FileText, Loader2, Network, RefreshCw, Sparkles } from 'lucide-react'
import { getMeetingReport, regenerateMeetingReport, getMeetingTranscript } from '../services/meetingReportService'
import Mindmap from './Mindmap'

function formatSec(sec = 0) {
  sec = Math.max(0, Math.floor(sec))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const colors = ['bg-violet-500', 'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-pink-500', 'bg-cyan-500']

export default function MeetingReportView({ sessionId }) {
  const [report, setReport] = useState(null)
  const [transcript, setTranscript] = useState(null)
  const [selectedBlock, setSelectedBlock] = useState(null)
  const [hoverBlockId, setHoverBlockId] = useState(null)
  const [selectedAiEvent, setSelectedAiEvent] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [errorText, setErrorText] = useState('')

  const totalSec = Math.max(1, report?.totalSec || 1)

  const activeBlock = useMemo(() => {
    if (!report?.topicBlocks?.length) return null
    return report.topicBlocks.find((b) => b.id === hoverBlockId) || selectedBlock || report.topicBlocks[0]
  }, [report, hoverBlockId, selectedBlock])

  const loadReport = async () => {
    if (!sessionId) {
      setErrorText('sessionId가 없습니다. 회의 종료 후 다시 들어오세요.')
      return
    }

    setIsLoading(true)
    setErrorText('')

    try {
      const data = await getMeetingReport(sessionId)
      setReport(data)
      setSelectedBlock(data.topicBlocks?.[0] || null)

      try {
        const t = await getMeetingTranscript(sessionId)
        setTranscript(t)
      } catch {
        setTranscript(null)
      }
    } catch (e) {
      setErrorText(e.message)
    } finally {
      setIsLoading(false)
    }
  }

  const handleRegenerate = async () => {
    if (!sessionId) return
    setIsRegenerating(true)
    setErrorText('')

    try {
      const data = await regenerateMeetingReport(sessionId)
      setReport(data)
      setSelectedBlock(data.topicBlocks?.[0] || null)
    } catch (e) {
      setErrorText(e.message)
    } finally {
      setIsRegenerating(false)
    }
  }

  useEffect(() => {
    loadReport()
  }, [sessionId])

  return (
    <div className="flex-1 h-full overflow-hidden bg-[#f7f8fb] flex flex-col">
      <header className="h-20 bg-white border-b border-gray-200 px-8 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-2xl font-black text-gray-900">회의 분석</h1>
          <p className="text-sm text-gray-500 mt-1">
            회의 종료 후 전체 STT를 SLM으로 다시 분석해 주제별 progress bar를 생성합니다.
          </p>
        </div>

        <button
          onClick={handleRegenerate}
          disabled={isRegenerating || !sessionId}
          className="h-11 px-4 rounded-2xl bg-gray-900 text-white font-semibold inline-flex items-center gap-2 disabled:opacity-50"
        >
          {isRegenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          전체 STT 재분석
        </button>
      </header>

      {(isLoading || isRegenerating) && (
        <div className="mx-8 mt-5 rounded-3xl bg-violet-50 border border-violet-100 p-6 flex items-center gap-3 text-violet-700">
          <Loader2 className="w-5 h-5 animate-spin" />
          {isRegenerating ? '회의 전체 STT를 SLM으로 다시 분석 중입니다.' : '회의 분석을 불러오는 중입니다.'}
        </div>
      )}

      {errorText && (
        <div className="mx-8 mt-5 rounded-2xl bg-red-50 text-red-600 px-5 py-4 text-sm">
          {errorText}
        </div>
      )}

      {!report && !isLoading ? (
        <div className="flex-1 flex items-center justify-center text-gray-400">
          표시할 회의 분석이 없습니다.
        </div>
      ) : report ? (
        <main className="flex-1 min-h-0 overflow-y-auto p-8 space-y-6">
          <section className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-sm text-violet-600 font-semibold">회의 제목</div>
                <h2 className="text-2xl font-black text-gray-900 mt-1">{report.session?.title || '회의'}</h2>
                <div className="text-sm text-gray-500 mt-2">
                  총 길이 {formatSec(totalSec)} · 주제 {report.topicBlocks?.length || 0}개 · AI 사용 {report.aiEvents?.length || 0}회
                </div>
              </div>
              <div className="text-xs rounded-2xl bg-gray-100 px-3 py-2 text-gray-600">
                {report.analysisMode || 'SLM_FULL_TRANSCRIPT_ANALYSIS'}
              </div>
            </div>

            <div className="mt-6">
              <div className="flex items-center gap-2 mb-3">
                <Clock className="w-4 h-4 text-gray-500" />
                <span className="text-sm font-bold text-gray-700">주제별 Progress Bar</span>
              </div>

              <div className="relative h-20 rounded-2xl bg-gray-100 border border-gray-200 overflow-hidden">
                {report.topicBlocks?.map((block, idx) => {
                  const left = (block.startSec / totalSec) * 100
                  const width = Math.max(2, ((block.endSec - block.startSec) / totalSec) * 100)
                  const active = hoverBlockId === block.id || selectedBlock?.id === block.id

                  return (
                    <button
                      key={block.id}
                      onMouseEnter={() => setHoverBlockId(block.id)}
                      onMouseLeave={() => setHoverBlockId(null)}
                      onClick={() => {
                        setSelectedBlock(block)
                        setSelectedAiEvent(null)
                      }}
                      className={`absolute top-0 h-full ${colors[idx % colors.length]} transition-all ${
                        active ? 'brightness-110 scale-y-105 z-10 ring-4 ring-black/10' : 'opacity-90 hover:opacity-100'
                      }`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      title={`${block.start}~${block.end} ${block.topic}`}
                    >
                      <div className="h-full flex flex-col justify-center text-left px-3 text-white overflow-hidden">
                        <div className="text-xs font-black truncate">{block.topic}</div>
                        <div className="text-[11px] opacity-90">{block.start}~{block.end}</div>
                      </div>
                    </button>
                  )
                })}

                {report.aiEvents?.map((event) => {
                  const left = (event.askedAtSec / totalSec) * 100
                  return (
                    <button
                      key={event.id}
                      onClick={() => setSelectedAiEvent(event)}
                      className="absolute top-0 bottom-0 w-[3px] bg-black z-20 hover:w-[5px]"
                      style={{ left: `${left}%` }}
                      title={`AI 질문 [${event.askedAt}] ${event.question}`}
                    >
                      <span className="absolute -top-1 -left-2 w-5 h-5 rounded-full bg-black text-white flex items-center justify-center">
                        <Bot className="w-3 h-3" />
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          </section>

          <section className="grid grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)] gap-6">
            <div className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
              <div className="flex items-center gap-2 mb-4">
                <Sparkles className="w-5 h-5 text-violet-600" />
                <h3 className="text-lg font-bold text-gray-900">선택 주제 상세</h3>
              </div>

              {activeBlock ? (
                <>
                  <div className="text-sm text-violet-600 font-bold">[{activeBlock.start}~{activeBlock.end}]</div>
                  <h4 className="text-2xl font-black text-gray-900 mt-1">{activeBlock.topic}</h4>
                  <p className="mt-4 text-sm text-gray-700 leading-7 whitespace-pre-wrap">{activeBlock.summary}</p>

                  <div className="mt-5 flex flex-wrap gap-2">
                    {(activeBlock.keywords || []).map((kw) => (
                      <span key={kw} className="rounded-full bg-violet-50 text-violet-700 px-3 py-1.5 text-sm">
                        {kw}
                      </span>
                    ))}
                  </div>

                  <div className="mt-6 rounded-2xl bg-gray-50 border border-gray-200 p-4 max-h-48 overflow-y-auto text-sm text-gray-700 whitespace-pre-wrap">
                    {activeBlock.text}
                  </div>
                </>
              ) : (
                <div className="text-gray-400">선택된 주제가 없습니다.</div>
              )}
            </div>

            <div className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
              <div className="flex items-center gap-2 mb-4">
                <Bot className="w-5 h-5 text-gray-900" />
                <h3 className="text-lg font-bold text-gray-900">AI 사용 시점</h3>
              </div>

              {selectedAiEvent ? (
                <div>
                  <div className="text-sm text-gray-500">[{selectedAiEvent.askedAt}]</div>
                  <div className="mt-3 rounded-2xl bg-gray-50 border border-gray-200 p-4">
                    <div className="text-xs font-bold text-gray-400 mb-1">질문</div>
                    <div className="text-sm">{selectedAiEvent.question}</div>
                  </div>
                  <div className="mt-3 rounded-2xl bg-violet-50 border border-violet-100 p-4">
                    <div className="text-xs font-bold text-violet-500 mb-1">응답</div>
                    <div className="text-sm whitespace-pre-wrap">{selectedAiEvent.answer || '응답 기록 없음'}</div>
                  </div>
                </div>
              ) : report.aiEvents?.length ? (
                <div className="space-y-3">
                  {report.aiEvents.map((event) => (
                    <button
                      key={event.id}
                      onClick={() => setSelectedAiEvent(event)}
                      className="w-full text-left rounded-2xl border border-gray-200 hover:bg-violet-50 hover:border-violet-300 p-4"
                    >
                      <div className="text-xs text-violet-600 font-bold">[{event.askedAt}]</div>
                      <div className="text-sm text-gray-800 mt-1 line-clamp-2">{event.question}</div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-gray-400">기록된 AI 질문이 없습니다.</div>
              )}
            </div>
          </section>

          <section className="grid grid-cols-2 gap-6">
            <div className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
              <div className="flex items-center gap-2 mb-4">
                <FileText className="w-5 h-5 text-blue-600" />
                <h3 className="text-lg font-bold text-gray-900">회의록 정리</h3>
              </div>
              <pre className="whitespace-pre-wrap text-sm leading-7 text-gray-700 bg-gray-50 rounded-2xl border border-gray-200 p-4 max-h-[520px] overflow-y-auto">
                {report.minutesMarkdown}
              </pre>
            </div>

            <div className="bg-white rounded-3xl border border-gray-200 shadow-sm overflow-hidden">
              <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-100">
                <Network className="w-5 h-5 text-emerald-600" />
                <h3 className="text-lg font-bold text-gray-900">주제 흐름 마인드맵</h3>
              </div>
              <div className="h-[520px]">
                <Mindmap text={report.mindmapText} />
              </div>
            </div>
          </section>

          {transcript && (
            <section className="bg-white rounded-3xl border border-gray-200 shadow-sm p-6">
              <h3 className="text-lg font-bold text-gray-900">STT 원문</h3>
              <div className="mt-4 max-h-[420px] overflow-y-auto rounded-2xl bg-gray-50 border border-gray-200 p-4">
                {transcript.transcriptLines?.map((line, idx) => (
                  <div key={idx} className="py-2 border-b border-gray-100 last:border-0">
                    <span className="text-xs font-bold text-violet-600">[{line.start}~{line.end}]</span>
                    <span className="ml-2 text-xs font-semibold text-gray-500">{line.speaker}</span>
                    <span className="ml-2 text-sm text-gray-800">{line.text}</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </main>
      ) : null}
    </div>
  )
}
