// frontend/src/components/MeetingTopicView.jsx
import React, { useState, useEffect } from 'react';

export default function MeetingTopicView() {
  const [topic, setTopic] = useState("분석 시작 대기 중...");

  const fetchTopic = async () => {
    try {
      const response = await fetch('http://127.0.0.1:8000/api/realtime-topic');
      const data = await response.json();
      if (data.topic) setTopic(data.topic);
    } catch (err) {
      console.error("주제 로드 실패:", err);
    }
  };

  useEffect(() => {
    fetchTopic(); // 초기 로드
    const interval = setInterval(fetchTopic, 30000); // 30초마다 슬라이딩 윈도우 분석
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="w-full max-w-4xl mx-auto my-6 animate-fade-in">
      <div className="bg-[#1e1f35]/80 backdrop-blur-md border border-white/10 rounded-3xl p-6 shadow-2xl flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
          <span className="text-gray-400 font-medium text-sm">실시간 주제 분석</span>
        </div>

        {/* 📍 여기가 핵심 시각화 영역: 볼드체 + 강조색상 */}
        <div className="flex-1 text-center">
          <h2 className="text-white text-3xl font-black tracking-tighter">
            " <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#9785f2] to-[#ff5e5e]">
              {topic}
            </span> "
          </h2>
        </div>

        <div className="text-[#86a0d4] text-[10px] font-mono uppercase tracking-widest">
          Sliding Window v3.0
        </div>
      </div>
    </div>
  );
}