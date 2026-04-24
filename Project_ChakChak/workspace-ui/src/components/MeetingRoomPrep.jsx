import React, { useState, useRef } from 'react';
import { Mic, ArrowUp, Bot, FileText, Clock, Key, Upload } from 'lucide-react';

//종범추가
// 회의실 UI 컴포넌트 내부 상단에 추가
// const [currentTopic, setCurrentTopic] = useState("주제를 파악 중입니다...");

// useEffect(() => {
//   const fetchTopic = async () => {
//     try {
//       const response = await fetch('http://127.0.0.1:8000/api/realtime-topic');
//       const data = await response.json();
//       setCurrentTopic(data.topic);
//     } catch (err) {
//       console.error("실시간 분석 오류:", err);
//     }
//   };

//   const timer = setInterval(fetchTopic, 30000); // 30초마다 갱신 (슬라이딩 윈도우)
//   return () => clearInterval(timer);
// }, []);

// // JSX 부분
// <div className="w-full py-4 text-center">
//   <h2 className="text-white text-2xl font-black tracking-tight">
//     현재 대화 주제: <span className="text-[#9785f2] border-b-2 border-[#ff5e5e]">{currentTopic}</span>
//   </h2>
// </div>
//종범추가

// 새로 추가된 KeywordTags 컴포넌트
function KeywordTags({ keywordsString }) {
  const keywordArray = keywordsString
    ? keywordsString.split(',').map(k => k.trim()).filter(k => k !== '')
    : [];

  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {keywordArray.length > 0 ? (
        keywordArray.map((keyword, index) => (
          <span 
            key={index}
            className="inline-flex items-center px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-[13px] font-medium text-gray-600 shadow-sm"
          >
            #{keyword}
          </span>
        ))
      ) : null}
    </div>
  );
}

export default function MeetingRoomPrep({ onStartMeeting }) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [isStarting, setIsStarting] = useState(false); 
  
  // 프롬프트로 전달할 데이터 상태
  const [planData, setPlanData] = useState({
    title: '',
    time: '',
    keywords: ''
  });

  const fileInputRef = useRef(null);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setPlanData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  //  서버로 데이터 전송 및 회의 시작 (핵심 연동 로직)
  const handleStartMeeting = async () => {
    // 1. 유효성 검사: 파일도 없고 텍스트 입력도 없으면 차단
    if (!selectedFile && (!planData.title && !planData.time && !planData.keywords)) {
      alert("회의 계획서 파일을 업로드하거나 회의 정보를 직접 입력해주세요.");
      return;
    }

    setIsStarting(true);
    
    // 서버로 보낼 데이터 포장
    const formData = new FormData();
    if (selectedFile) {
      formData.append("file", selectedFile);
    } else {
      formData.append("topic", planData.title);
      formData.append("time", planData.time);
      formData.append("keywords", planData.keywords);
    }

    try {
      // FastAPI 서버로 POST 요청
      const response = await fetch("http://127.0.0.1:8000/api/document/extract/", {
        method: "POST",
        body: formData
      });
      
      const result = await response.json();
      
      if (result.status === "success") {
        console.log("✅ 텍스트 추출 및 DB 저장 성공:", result);
        alert("회의 준비가 완료되었습니다!");
        
        // 부모 컴포넌트로 추출된 텍스트와 DB record_id까지 함께 넘겨줌
        onStartMeeting({
          ...planData,
          recordId: result.record_id,
          extractedText: result.text
        });
      } else {
        alert("❌ 오류 발생: " + result.message);
      }
    } catch (error) {
      console.error(error);
      alert("서버와 통신할 수 없습니다. 백엔드(FastAPI) 서버가 켜져 있는지 확인해주세요.");
    } finally {
      setIsStarting(false);
    }
  };

  // 파일 업로드 관련 핸들러
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) {
      alert("파일 크기는 50MB를 초과할 수 없습니다.");
      e.target.value = ''; 
      return;
    }
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    // HWP, HWPX 지원 추가
    if (!['.pdf', '.docx', '.txt', '.hwp', '.hwpx'].includes(ext)) {
      alert("지원하지 않는 파일 형식입니다. (PDF, DOCX, TXT, HWP, HWPX만 가능)");
      e.target.value = '';
      return;
    }
    setSelectedFile(file);
  };

  const handleDragOver = (e) => e.preventDefault();
  const handleDrop = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (file.size > 50 * 1024 * 1024) return alert("파일 크기는 50MB를 초과할 수 없습니다.");
      const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
      // HWP, HWPX 지원 추가
      if (!['.pdf', '.docx', '.txt', '.hwp', '.hwpx'].includes(ext)) return alert("지원하지 않는 파일 형식입니다.");
      setSelectedFile(file);
    }
  };

  // 모달 내 완료 버튼: 파일 상태는 유지하고 창만 닫기
  const handleConfirmFile = () => {
    if (!selectedFile) {
      alert("파일을 먼저 선택해주세요.");
      return;
    }
    setIsModalOpen(false);
  };

  return (
    <div className="w-full min-h-screen bg-[#141525] flex flex-col items-center py-12 px-8 overflow-y-auto font-sans">
      
      {/* Title */}
      <div className="w-full max-w-5xl mb-6">
        <h1 className="text-white text-[26px] font-extrabold tracking-wide">회의계획서 업로드</h1>
      </div>

      {/* Top Section */}
      <div className="w-full max-w-5xl bg-gradient-to-br from-[#3b66c4] to-[#2c4e9e] rounded-[2.5rem] p-8 flex flex-col md:flex-row gap-8 shadow-2xl relative">
        
        {/* Left Card: File Upload */}
        <div className="flex-1 bg-white/95 backdrop-blur-sm rounded-[2rem] p-8 flex flex-col items-center justify-center text-center shadow-inner">
          <p className="text-[#2c4e9e] font-semibold mb-8 text-[16px]">
            작성된 회의계획서를 업로드할 수 있습니다
          </p>
          <button 
            onClick={() => setIsModalOpen(true)}
            className="bg-gradient-to-r from-[#9785f2] to-[#806cf0] text-white px-10 py-3.5 rounded-full font-bold hover:shadow-lg hover:-translate-y-1 transition-all duration-300"
          >
            파일 선택
          </button>
          
          {/* 선택된 파일이 있을 경우 메인 화면에 표시 */}
          {selectedFile && (
            <p className="mt-5 text-[14px] font-bold text-[#845ef7] animate-fade-in">
              📎 {selectedFile.name}
            </p>
          )}
        </div>

        {/* Right Card: Manual Input Form */}
        <div className="w-full md:w-[55%] flex flex-col justify-between">
          <div className="bg-white rounded-[2rem] p-8 shadow-inner flex-1">
            <h3 className="text-[#2c4e9e] font-bold mb-6 text-[16px]">회의계획서 입력</h3>
            <div className="space-y-4">
              
              <div className="flex items-center bg-[#f3f5fa] rounded-2xl px-5 py-3 focus-within:ring-2 focus-within:ring-[#9785f2] transition-all focus-within:bg-white shadow-sm">
                <FileText className="text-gray-400 mr-3 h-5 w-5 flex-shrink-0" />
                <input 
                  name="title" value={planData.title} onChange={handleInputChange}
                  placeholder="주제" 
                  disabled={selectedFile !== null} // 파일이 있으면 입력 비활성화 (선택 사항)
                  className="flex-1 bg-transparent outline-none text-[15px] font-medium text-gray-700 placeholder-gray-400 disabled:opacity-50"
                />
              </div>

              <div className="flex items-center bg-[#f3f5fa] rounded-2xl px-5 py-3 focus-within:ring-2 focus-within:ring-[#9785f2] transition-all focus-within:bg-white shadow-sm">
                <Clock className="text-gray-400 mr-3 h-5 w-5 flex-shrink-0" />
                <input 
                  name="time" value={planData.time} onChange={handleInputChange}
                  placeholder="회의 시간" 
                  disabled={selectedFile !== null}
                  className="flex-1 bg-transparent outline-none text-[15px] font-medium text-gray-700 placeholder-gray-400 disabled:opacity-50"
                />
              </div>

              <div className="flex items-center bg-[#f3f5fa] rounded-2xl px-5 py-3 focus-within:ring-2 focus-within:ring-[#9785f2] transition-all focus-within:bg-white shadow-sm">
                <Key className="text-gray-400 mr-3 h-5 w-5 flex-shrink-0" />
                <input 
                  name="keywords" value={planData.keywords} onChange={handleInputChange}
                  placeholder="회의 키워드 (쉼표로 구분)" 
                  disabled={selectedFile !== null}
                  className="flex-1 bg-transparent outline-none text-[15px] font-medium text-gray-700 placeholder-gray-400 disabled:opacity-50"
                />
              </div>

              {planData.keywords && (
                <div className="px-1 pt-1 animate-fade-in">
                  <KeywordTags keywordsString={planData.keywords} />
                </div>
              )}

            </div>
          </div>
          
          <div className="mt-4 flex justify-end px-2">
            <p className="text-[12px] text-[#86a0d4] font-medium">
              계획서가 없을 시 AI 어시스턴트의 이해를 돕기 위해 회의에 대한 설명해주세요
            </p>
          </div>
        </div>
      </div>

      {/* Center Action Button */}
      <div className="my-10">
        <button 
          onClick={handleStartMeeting}
          disabled={isStarting}
          className="bg-gradient-to-r from-[#3b66c4] to-[#2c4e9e] text-white text-[20px] font-bold px-12 py-4 rounded-[2rem] shadow-xl hover:shadow-2xl hover:-translate-y-1 active:translate-y-0 disabled:opacity-70 disabled:cursor-wait transition-all duration-300 flex items-center justify-center gap-3"
        >
          {isStarting ? (
             <span>⏳ 처리 중...</span>
          ) : (
            <>
              <Mic className="text-[#ff5e5e] fill-[#ff5e5e] h-6 w-6" /> 
              <span>회의 시작</span>
            </>
          )}
        </button>
      </div>

      {/* Bottom AI Assistant Card */}
      <div className="w-full max-w-5xl bg-gradient-to-br from-[#3b66c4] to-[#2c4e9e] rounded-[2.5rem] py-14 px-8 flex flex-col items-center justify-center shadow-2xl relative">
        <div className="w-[80px] h-[80px] bg-[#f05c5f] rounded-full flex items-center justify-center mb-6 shadow-lg border-4 border-white/20">
          <Bot className="w-10 h-10 text-white" />
        </div>
        
        <h2 className="text-white text-[24px] font-bold mb-10 tracking-wide text-shadow-sm">
          AI 어시스턴스 착착이 참여 완료!
        </h2>
        
        <div className="w-full max-w-[650px] bg-white rounded-full flex items-center px-2 py-2 shadow-inner">
          <input 
            placeholder="회의가 시작되면 AI 어시스턴트가 활성화됩니다" 
            className="flex-1 bg-transparent px-5 py-2.5 outline-none text-[15px] font-medium text-gray-500 placeholder-gray-400" 
            disabled
          />
          <button className="bg-gray-500 text-white p-2.5 rounded-full shadow-sm cursor-not-allowed">
            <ArrowUp className="h-5 w-5" />
          </button>
        </div>
        
        <p className="absolute bottom-5 text-center text-[#86a0d4] text-[12px] font-medium">
          AI 어시스턴트는 실수를 할 수 있습니다
        </p>
      </div>

      {/* File Upload Modal Overlay */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-[2rem] shadow-2xl w-full max-w-[550px] p-8 flex flex-col transform transition-all">
            <h2 className="text-[18px] font-extrabold text-gray-800 mb-6">회의계획서를 업로드하세요</h2>
            
            <div 
              className="border-2 border-dashed border-gray-300 rounded-[1.5rem] p-12 flex flex-col items-center justify-center hover:bg-[#f3f5fa] hover:border-[#9785f2] transition-colors mb-6 relative cursor-pointer"
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current.click()}
            >
              <input 
                type="file" ref={fileInputRef} className="hidden" 
                accept=".pdf,.docx,.txt,.hwp,.hwpx" onChange={handleFileChange}
              />
              <div className="w-16 h-16 bg-[#9785f2] rounded-full flex items-center justify-center mb-4 shadow-md">
                <Upload className="h-8 w-8 text-white" />
              </div>
              <p className="text-[15px] font-bold text-gray-700 mb-1">여기로 파일을 드래그 앤 드롭하세요</p>
              <p className="text-[13px] text-gray-500 mb-4">또는</p>
              <button 
                className="border border-[#9785f2] text-[#9785f2] px-6 py-2.5 rounded-full text-sm font-bold shadow-sm hover:bg-[#f3f5fa] transition-colors"
                onClick={(e) => {
                  e.stopPropagation(); // 버튼 클릭 시 부모의 onClick(파일 선택) 방지
                  fileInputRef.current.click();
                }}
              >
                {selectedFile ? selectedFile.name : '파일 선택'}
              </button>
              <p className="absolute bottom-4 text-[12px] text-gray-400 font-medium mt-5">지원 형식: PDF, DOCX, TXT, HWP, HWPX · 최대 50MB</p>
            </div>

            <div className="flex justify-end gap-3 mt-2">
              <button 
                onClick={() => { setIsModalOpen(false); setSelectedFile(null); }}
                className="px-6 py-2.5 border border-gray-200 rounded-xl text-gray-600 font-bold hover:bg-gray-50 text-[14px] transition-colors"
              >
                취소
              </button>
              <button 
                onClick={handleConfirmFile}
                className="px-6 py-2.5 bg-gray-800 text-white rounded-xl font-bold hover:bg-black text-[14px] shadow-sm flex items-center transition-colors"
              >
                완료
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}