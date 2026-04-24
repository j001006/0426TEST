import React, { useState, useRef, useEffect } from 'react';
import { Mic, Users, Activity, Bot, Sparkles, Pause, Square, Send, FileAudio } from 'lucide-react';
import { chatWithAI, summarizeMeeting } from '../services/aiService';
import STTWorkspace from './STTWorkspace';
import AIInsightPanel from './AIInsightPanel';


import AgendaSidebar from './AgendaSidebar'; 

export default function MeetingLiveView({ planData }) {
  // 업로드된 데이터가 없을 경우 표시할 기본값
  const data = planData || {
    title: "새로운 즉석 회의", 
    time: "진행 중", 
    keywords: "자유주제" 
  };
  
  // 아젠다가 없을 경우 기본 메시지
  const agendas = data.agendas || ["회의 안건을 기반으로 논의를 시작하세요."];

  // 대화 내역 상태
  const [messages, setMessages] = useState([
    { sender: 'ai', text: '회의가 시작되었습니다. 우측의 STT 기능을 통해 음성을 올리고 아이디어를 물어보세요!' }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);
  
  // STT 패널 열기/닫기 (공간 확보용)
  const [isSttOpen, setIsSttOpen] = useState(true);

  // 실시간 AI 요약 패널 상태
  const [aiResult, setAiResult] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // 종범추가 실시간 주제 상태
  const [currentTopic, setCurrentTopic] = useState("대화 분석 중...");
  //

  // 스크롤을 항상 최하단으로 내리는 함수
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  //종범추가 실시간 주제 가져오기 로직
  useEffect(() => {
    const fetchTopic = async () => {
      try {
        const response = await fetch('http://127.0.0.1:8000/api/realtime-topic');
        const data = await response.json();
        if (data.topic) setCurrentTopic(data.topic);
      } catch (err) {
        console.error("실시간 주제 분석 오류:", err);
      }
    };

    fetchTopic(); // 처음 로드될 때 한 번 실행
    const timer = setInterval(fetchTopic, 30000); // 30초마다 반복 실행
    return () => clearInterval(timer); // 컴포넌트 종료 시 타이머 해제
  }, []);
  //

  // 메시지 전송 로직
  const handleSendMessage = async (text) => {
    const trimmedText = text.trim();
    if (!trimmedText || isLoading) return;
    
    setMessages((prev) => [...prev, { sender: 'user', text: trimmedText }]);
    setInputValue('');
    setIsLoading(true);

    try {
      const response = await chatWithAI(trimmedText);
      setMessages((prev) => [...prev, { sender: 'ai', text: response }]);
    } catch (error) {
      console.error(error);
      setMessages((prev) => [
        ...prev, 
        { sender: 'ai', text: '네트워크 연결이 지연되고 있거나 AI 서버 오류가 발생했습니다. 다시 시도해주세요.' }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSendMessage(inputValue);
    }
  };

  // 요약 데이터 불러오기
  const handleFetchInsight = async () => {
    setIsAnalyzing(true);
    try {
      const sessionId = data.sessionId || 1;
      const result = await summarizeMeeting(sessionId);
      setAiResult(result);
    } catch (error) {
      console.error('요약 가져오기 실패:', error);
      alert('AI 요약 데이터를 가져오는 중 오류가 발생했습니다.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="w-full h-full flex bg-[#131521] overflow-hidden font-sans">
      
      <AgendaSidebar data={data} agendas={agendas} />

      {/* 2. Main Center */}
      <div className="flex-1 flex flex-col relative p-6 min-h-0">
        
        {/* Top Header info */}
        <div className="flex justify-end items-center mb-3 px-2 shrink-0">
          <button 
            onClick={() => setIsSttOpen(!isSttOpen)}
            className="mr-3 px-3 py-1.5 rounded-full border border-white/20 text-white/80 text-xs hover:bg-white/10 transition-colors flex items-center gap-2"
          >
            <FileAudio className="w-3 h-3" />
            {isSttOpen ? 'STT 패널 접기' : 'STT 패널 열기'}
          </button>
          <div className="flex items-center bg-white/10 backdrop-blur-md px-4 py-2 rounded-full border border-white/5 shadow-lg">
            <Users className="w-4 h-4 text-white/70 mr-2" />
            <span className="text-white/90 font-medium text-[13px]">참여자 4명</span>
          </div>
        </div>

        //종범추가
        <div className="w-full mb-4 animate-in fade-in slide-in-from-top-4 duration-700">
          <div className="bg-[#1e1f35] rounded-3xl py-5 px-8 border border-white/10 shadow-2xl flex items-center justify-between">
            <div className="flex items-center gap-3 shrink-0">
              <div className="w-2.5 h-2.5 bg-rose-500 rounded-full animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.6)]" />
              <span className="text-gray-400 font-bold text-[11px] uppercase tracking-[0.2em]">Live Context</span>
            </div>
            
            <div className="flex-1 text-center">
              <h2 className="text-white text-2xl font-black tracking-tight">
                " <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#9785f2] to-[#ff5e5e]">{currentTopic}</span> "
              </h2>
            </div>

            <div className="flex items-center gap-2 shrink-0 text-white/30 text-[10px] font-mono">
              <Activity className="w-3 h-3" />
              ANALYZING...
            </div>
          </div>
        </div>
        //

        {/* STT Workspace Area */}
        {isSttOpen && (
          <div className="bg-white rounded-3xl shadow-2xl mb-4 flex flex-col overflow-hidden border border-white/20 h-[45vh] shrink-0 transition-all duration-300">
            <div className="bg-slate-50 border-b border-gray-100 py-3 px-6 flex items-center justify-between shrink-0">
               <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><Mic className="w-4 h-4 text-blue-600"/> 음성 기록 및 변환 (STT)</h3>
            </div>
            <STTWorkspace />
          </div>
        )}

        {/* The Main Container */}
        <div className="flex-1 bg-white rounded-[2rem] shadow-2xl flex flex-col md:flex-row overflow-hidden border border-white/20 min-h-0">
          
          {/* Left: Chatting area */}
          <div className="flex-1 flex flex-col border-r border-gray-100 bg-white min-w-[300px]">
            <div className="flex items-center px-8 py-5 border-b border-gray-50 bg-white z-10 shadow-sm">
              <Bot className="w-5 h-5 text-blue-600 mr-2" />
              <h2 className="text-[15px] font-extrabold text-gray-800 tracking-tight">AI 실시간 어시스턴트</h2>
            </div>
            
            {/* Messages */}
            <div className="flex-1 p-8 overflow-y-auto space-y-6 bg-slate-50/30">
              {messages.map((msg, idx) => (
                msg.sender === 'user' ? (
                  <div key={idx} className="flex justify-end transform transition-all duration-300">
                    <div className="bg-[#48c78e] text-white px-5 py-3.5 rounded-3xl rounded-tr-sm max-w-[80%] shadow-[0_4px_14px_0_rgba(72,199,142,0.39)] font-medium text-[14px]">
                      {msg.text}
                    </div>
                  </div>
                ) : (
                  <div key={idx} className="flex justify-start items-start gap-4 transform transition-all duration-300">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-rose-400 to-rose-600 flex items-center justify-center text-white shrink-0 shadow-lg shadow-rose-500/30">
                      <Bot className="w-5 h-5" />
                    </div>
                    <div className="bg-[#2c2b3e] text-white px-6 py-5 rounded-3xl rounded-tl-sm max-w-[85%] shadow-md font-medium text-[14px] leading-relaxed whitespace-pre-wrap">
                      {msg.text}
                    </div>
                  </div>
                )
              ))}

              {isLoading && (
                <div className="flex justify-start items-start gap-4">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-rose-400 to-rose-600 flex items-center justify-center text-white shrink-0 shadow-lg shadow-rose-500/30">
                    <Bot className="w-5 h-5 animate-pulse" />
                  </div>
                  <div className="bg-[#2c2b3e] h-12 w-[80px] rounded-3xl rounded-tl-sm shadow-md flex items-center justify-center gap-1.5 opacity-80">
                    <span className="w-2 h-2 bg-white rounded-full animate-bounce"></span>
                    <span className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                    <span className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} className="h-4" />
            </div>
            
            {/* Input Box */}
            <div className="p-6 bg-white border-t border-gray-50">
              <div className="relative group">
                <input 
                  type="text" 
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={isLoading ? "AI가 답변을 작성하고 있습니다..." : "AI 어시스턴트에게 질문해보세요"} 
                  disabled={isLoading}
                  className="w-full bg-gray-50 border border-gray-200 rounded-full py-4 pl-6 pr-14 text-[14px] focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all font-medium placeholder-gray-400 disabled:opacity-60 disabled:bg-gray-100"
                />
                <button 
                  onClick={() => handleSendMessage(inputValue)}
                  disabled={isLoading || !inputValue.trim()}
                  className="absolute right-2 top-1/2 -translate-y-1/2 w-10 h-10 bg-[#3a394c] group-hover:bg-blue-600 rounded-full flex items-center justify-center text-white transition-colors duration-300 shadow-md disabled:bg-gray-300 disabled:cursor-not-allowed">
                  <Send className="w-4 h-4 ml-0.5" />
                </button>
              </div>
              <p className="text-center text-[11px] text-gray-400 mt-3 font-semibold">AI 어시스턴트는 실수를 할 수 있습니다</p>
            </div>
          </div>

          {/* Right: Side Panels */}
          <div className="w-full md:w-[420px] bg-[#f8f9fc] p-6 flex flex-col gap-5 shrink-0 border-l border-gray-100">
            
            <div className="flex justify-end -mb-1">
              <button 
                onClick={handleFetchInsight}
                className="text-[16px] text-indigo-500 hover:text-indigo-700 font-bold transition-colors underline underline-offset-2 flex items-center gap-1"
                disabled={isAnalyzing}
              >
                <Activity className="w-3 h-3" />
                현재까지 진행 내용 요약하기
              </button>
            </div>

            <div className="flex-1 min-h-0 overflow-hidden relative flex flex-col">
              {isAnalyzing ? (
                <div className="flex-1 flex flex-col items-center justify-center p-6 bg-gradient-to-br from-[#eef2ff] to-[#f8fafc] rounded-3xl border border-indigo-100 shadow-inner">
                  <div className="relative mb-6">
                    <div className="absolute inset-0 bg-indigo-400 rounded-full blur-xl animate-pulse opacity-40"></div>
                    <div className="w-16 h-16 bg-indigo-500 rounded-full flex items-center justify-center relative z-10 shadow-lg shadow-indigo-200 animate-bounce">
                      <Bot className="w-8 h-8 text-white" />
                    </div>
                  </div>
                  <h3 className="text-[15px] font-extrabold text-indigo-900 mb-3">착착이가 회의를 분석하고 있어요!</h3>
                  <div className="flex items-center gap-1.5 mb-4">
                    <span className="w-2 h-2 bg-indigo-400 rounded-full animate-pulse"></span>
                    <span className="w-2 h-2 bg-indigo-400 rounded-full animate-pulse" style={{ animationDelay: '150ms' }}></span>
                    <span className="w-2 h-2 bg-indigo-400 rounded-full animate-pulse" style={{ animationDelay: '300ms' }}></span>
                  </div>
                  <p className="text-[12px] text-indigo-500/80 font-medium text-center leading-relaxed">
                    현재까지 진행된 회의 내용을<br/>정리하는 중입니다... 잠시만 기다려주세요.
                  </p>
                </div>
              ) : aiResult ? (
                <AIInsightPanel aiResult={aiResult} isAnalyzing={isAnalyzing} />
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center p-6 bg-white rounded-3xl border-2 border-dashed border-gray-200 hover:border-indigo-300 transition-colors group cursor-default">
                  <div className="w-16 h-16 bg-[#f3f5fa] group-hover:bg-indigo-50 rounded-2xl rotate-3 group-hover:-rotate-3 transition-all duration-300 flex items-center justify-center mb-5 shadow-sm">
                    <Sparkles className="w-8 h-8 text-[#86a0d4] group-hover:text-indigo-500 transition-colors" />
                  </div>
                  <h3 className="text-[15px] font-bold text-gray-700 mb-2">착착이에게 요약을 요청해보세요!</h3>
                  <p className="text-[12px] text-gray-400 text-center leading-relaxed font-medium">
                    우측 상단의 <span className="text-indigo-500 font-bold bg-indigo-50 px-1.5 py-0.5 rounded">현재까지 진행 내용 요약하기</span>를 누르면<br/>
                    복잡한 회의 내용을 한눈에 정리해 드려요 ✨
                  </p>
                </div>
              )}
            </div>

            <div className="bg-white rounded-[2rem] border border-gray-100 shadow-sm p-6 flex flex-col shrink-0">
              <h3 className="text-[#414d6c] font-extrabold text-[15px] mb-4 flex items-center gap-2">
                <Bot className="w-4 h-4 text-blue-500" /> 착착이에게 즉시 요청하기
              </h3>
              <div className="space-y-2.5 flex-1 flex flex-col justify-center">
                <button 
                  onClick={() => handleSendMessage("현재까지 진행 내용 요약이 필요해요")}
                  disabled={isLoading}
                  className="w-full text-left px-5 py-3 rounded-2xl border border-gray-100 bg-gray-50 text-gray-700 font-bold text-[13px] hover:border-blue-200 hover:bg-blue-50/50 hover:text-blue-700 transition-all shadow-sm disabled:opacity-50">
                  📋 현재까지 진행 내용 요약이 필요해요
                </button>
                <button 
                  onClick={() => handleSendMessage("회의가 정체됐어. 어떻게 해결하면 좋을지 제안해줘")}
                  disabled={isLoading}
                  className="w-full text-left px-5 py-3 rounded-2xl border border-gray-100 bg-gray-50 text-gray-700 font-bold text-[13px] hover:border-blue-200 hover:bg-blue-50/50 hover:text-blue-700 transition-all shadow-sm disabled:opacity-50">
                  💡 회의가 정체됐어요. 제안해 주세요.
                </button>
                <button 
                  onClick={() => handleSendMessage("현재 상황에서 다음 단계(Next Step) 추천이 필요해")}
                  disabled={isLoading}
                  className="w-full text-left px-5 py-3 rounded-2xl border border-gray-100 bg-gray-50 text-gray-700 font-bold text-[13px] hover:border-blue-200 hover:bg-blue-50/50 hover:text-blue-700 transition-all shadow-sm disabled:opacity-50">
                  🚀 다음 스텝(Next Step) 추천이 필요해요
                </button>
              </div>
            </div>
          </div>

        </div>

        {/* Bottom Buttons */}
        <div className="flex justify-end gap-3 mt-6 pb-2 mr-2">
          <button className="flex items-center gap-2 px-6 py-3.5 bg-[#404b6b] hover:bg-[#4b587d] text-white font-bold text-[14px] rounded-xl transition-colors shadow-lg">
             <Pause className="w-4 h-4" fill="currentColor" /> 회의 일시멈춤
          </button>
          <button className="flex items-center gap-2 px-6 py-3.5 bg-[#2d7df6] hover:bg-[#2068db] text-white font-bold text-[14px] rounded-xl shadow-[0_0_15px_rgba(45,125,246,0.4)] transition-all transform hover:-translate-y-0.5">
             <Square className="w-4 h-4 ml-0.5" fill="currentColor" /> 회의 종료
          </button>
        </div>
      
      </div>
    </div>
  );
}