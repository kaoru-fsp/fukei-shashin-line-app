import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { X, ChevronLeft, ChevronRight, Camera, Aperture, Settings, MapPin, Calendar, Award, Sparkles, Loader2 } from 'lucide-react';

interface ContestPhoto {
  id?: string;
  Published?: string;
  PicFileName?: string;
  generatedImageUrl?: string;
  Title?: string;
  Winner?: string;
  Winner4Search?: string;
  Area?: string;
  Place?: string;
  Month?: string;
  Day?: string;
  Subject?: string;
  // EXIF and Tech Info
  Camera?: string;
  Lens?: string;
  Exposure?: string;
  DataOfPhoto?: string;
  Weather?: string;
  Composition?: string;
  Hour?: string;
  Year?: string;
}

interface FullScreenGalleryProps {
  photos: ContestPhoto[];
  initialIndex?: number;
  onClose: () => void;
}

const getPhotoUrl = (p: ContestPhoto) => {
  if (p.generatedImageUrl) return p.generatedImageUrl;
  const published = p.Published?.trim();
  const picFileName = p.PicFileName?.trim();
  if (!published || !picFileName) return '';
  const year = published.substring(0, 4);
  return `https://fupc.photo/PicsDB/PicsDB4Search/${year}/${published}/${picFileName}`.replace(/\/\/+/g, '/').replace('https:/', 'https://');
};

export default function FullScreenGallery({ photos, initialIndex = 0, onClose }: FullScreenGalleryProps) {
  const [currentIndex, setCurrentIndex] = useState(initialIndex);
  const [isPlaying, setIsPlaying] = useState(true);
  const [aiInsight, setAiInsight] = useState<string | null>(null);
  const [isAiLoading, setIsAiLoading] = useState(false);

  // Filter out photos that don't have valid URLs
  const validPhotos = photos.map(p => ({ ...p, url: getPhotoUrl(p) })).filter(p => !!p.url);

  useEffect(() => {
    // Reset AI insight when photo changes
    setAiInsight(null);
    setIsAiLoading(false);
  }, [currentIndex]);

  useEffect(() => {
    if (!isPlaying || validPhotos.length <= 1) return;
    const timer = setInterval(() => {
      setCurrentIndex((prev) => (prev + 1) % validPhotos.length);
    }, 5000);
    return () => clearInterval(timer);
  }, [isPlaying, validPhotos.length]);

  // Handle keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight') handleNext();
      if (e.key === 'ArrowLeft') handlePrev();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [validPhotos.length]);

  const handleNext = () => {
    setIsPlaying(false);
    setCurrentIndex((prev) => (prev + 1) % validPhotos.length);
  };

  const handlePrev = () => {
    setIsPlaying(false);
    setCurrentIndex((prev) => (prev - 1 + validPhotos.length) % validPhotos.length);
  };

  const fetchAiInsight = async (photo: ContestPhoto) => {
    setIsPlaying(false);
    setIsAiLoading(true);
    setAiInsight(null);

    const prompt = `あなたはプロの風景写真家です。以下の風景写真コンテスト入賞作品のメタデータを見て、この写真の素晴らしいポイント（構図、露出、レンズ選択、被写体の選び方など）を初心者の写真愛好家に向けて150文字程度で情熱的に解説してください。

【作品情報】
タイトル: ${photo.Title || "無題"}
撮影地: ${photo.Area || ""} ${photo.Place || ""}
時期: ${photo.Month || ""}月 ${photo.Hour ? photo.Hour + "時頃" : ""}
被写体: ${photo.Subject || "不明"}
【カメラ設定】
カメラ: ${photo.Camera || "不明"}
レンズ: ${photo.Lens || "不明"}
露出: ${photo.Exposure || "不明"}
フィルム/三脚: ${photo.DataOfPhoto || "不明"}
構図: ${photo.Composition || "不明"}
`;

    try {
      const response = await fetch('/api/gemini', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'generateContent', request: prompt })
      });
      
      const data = await response.json();
      if (data.text) {
        setAiInsight(data.text);
      } else {
        setAiInsight("AIによる解析を完了できませんでした。もう一度お試しください。");
      }
    } catch (e) {
      console.error(e);
      setAiInsight("ネットワークエラーによりAI解析が実行できませんでした。");
    } finally {
      setIsAiLoading(false);
    }
  };

  if (validPhotos.length === 0) {
    return (
      <div className="fixed inset-0 z-50 bg-black flex items-center justify-center">
        <div className="text-white">表示できる写真がありません。</div>
        <button onClick={onClose} className="absolute top-6 right-6 text-white p-2 bg-white/10 rounded-full">
          <X className="w-6 h-6" />
        </button>
      </div>
    );
  }

  const currentPhoto = validPhotos[currentIndex];

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[100] bg-black text-white flex flex-col"
    >
      {/* Top bar */}
      <div className="absolute top-0 inset-x-0 p-6 z-20 flex justify-between items-center bg-gradient-to-b from-black/80 to-transparent">
        <div className="text-emerald-400 font-serif font-bold text-xl tracking-widest uppercase flex items-center gap-2">
          Inspiration Gallery <span className="text-emerald-400/50 text-sm font-mono">PRO</span>
        </div>
        <button 
          onClick={onClose}
          className="p-2 bg-white/10 hover:bg-white/20 backdrop-blur-md rounded-full transition-colors border border-white/10"
        >
          <X className="w-6 h-6" />
        </button>
      </div>

      {/* Main Image Area */}
      <div className="relative flex-1 flex flex-col md:flex-row">
        <div className="relative flex-1 flex items-center justify-center overflow-hidden bg-stone-950">
          <AnimatePresence mode="wait">
            <motion.img
              key={currentPhoto.url}
              src={currentPhoto.url}
              alt={currentPhoto.Title || "Selected Photo"}
              initial={{ opacity: 0, scale: 1.05 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.8, ease: "easeInOut" }}
              className="absolute inset-0 w-full h-full object-contain z-0"
            />
          </AnimatePresence>

          {/* Navigation Buttons */}
          {validPhotos.length > 1 && (
            <>
              <button 
                onClick={handlePrev}
                className="absolute left-6 z-20 p-4 bg-black/40 hover:bg-black/80 backdrop-blur-sm rounded-full text-white/50 hover:text-white transition-all border border-white/10 group"
              >
                <ChevronLeft className="w-8 h-8 group-hover:-translate-x-1 transition-transform" />
              </button>
              <button 
                onClick={handleNext}
                className="absolute right-6 z-20 p-4 bg-black/40 hover:bg-black/80 backdrop-blur-sm rounded-full text-white/50 hover:text-white transition-all border border-white/10 group"
              >
                <ChevronRight className="w-8 h-8 group-hover:translate-x-1 transition-transform" />
              </button>
            </>
          )}
        </div>
        
        {/* Right Sidebar for EXIF and AI (desktop) or bottom drawer (mobile) */}
        <div className="w-full md:w-[400px] lg:w-[450px] bg-stone-900 border-l border-white/10 flex flex-col z-20 shrink-0 h-[50vh] md:h-auto overflow-y-auto">
          <div className="p-6 md:p-8 flex-1 flex flex-col">
            <div className="mb-6 pb-6 border-b border-white/10">
              <h2 className="text-2xl md:text-3xl font-serif font-bold text-white mb-3">
                {currentPhoto.Title || "無題"}
              </h2>
              <div className="flex flex-col gap-2 text-sm text-gray-400 font-serif">
                <span className="flex items-center gap-2">
                  <MapPin className="w-4 h-4 text-emerald-400/80" />
                  {[currentPhoto.Area, currentPhoto.Place].filter(Boolean).join("・")}
                </span>
                <span className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-emerald-400/80" />
                  {currentPhoto.Year ? `${currentPhoto.Year}年 ` : ""}{currentPhoto.Month}月{currentPhoto.Day ? ` ${currentPhoto.Day}日` : ""}{currentPhoto.Hour ? ` ${currentPhoto.Hour}時頃` : ""} 撮影
                </span>
                {currentPhoto.Winner4Search && (
                  <span className="flex items-center gap-2 text-emerald-300 font-medium">
                    <Award className="w-4 h-4" />
                    Photographed by {currentPhoto.Winner4Search}
                  </span>
                )}
              </div>
            </div>

            <div className="bg-white/5 border border-white/10 rounded-xl p-5 mb-6">
              <h3 className="text-xs font-bold text-emerald-400/80 uppercase tracking-widest mb-3 flex items-center gap-2 border-b border-white/10 pb-2">
                <Settings className="w-3.5 h-3.5" /> Technical Data
              </h3>
              <div className="grid grid-cols-2 gap-x-4 gap-y-4 font-mono text-xs text-gray-300">
                <div className="flex flex-col">
                  <span className="text-gray-500 text-[10px] uppercase mb-0.5 flex items-center gap-1"><Camera className="w-3 h-3" /> Camera</span>
                  <span className="break-words" title={currentPhoto.Camera || "N/A"}>{currentPhoto.Camera || "N/A"}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-gray-500 text-[10px] uppercase mb-0.5 flex items-center gap-1"><Aperture className="w-3 h-3" /> Lens</span>
                  <span className="break-words" title={currentPhoto.Lens || "N/A"}>{currentPhoto.Lens || "N/A"}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-gray-500 text-[10px] uppercase mb-0.5">Exposure</span>
                  <span>{currentPhoto.Exposure || "N/A"}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-gray-500 text-[10px] uppercase mb-0.5">Film / Tripod</span>
                  <span className="break-words" title={currentPhoto.DataOfPhoto || "N/A"}>{currentPhoto.DataOfPhoto || "N/A"}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-gray-500 text-[10px] uppercase mb-0.5">Subject / Weather</span>
                  <span>{currentPhoto.Subject || "N/A"} / {currentPhoto.Weather || "N/A"}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-gray-500 text-[10px] uppercase mb-0.5">Composition</span>
                  <span>{currentPhoto.Composition || "N/A"}</span>
                </div>
              </div>
            </div>

            {/* AI Assistant Insight Box */}
            <div className="mt-auto">
              {!aiInsight && !isAiLoading ? (
                <button
                  onClick={() => fetchAiInsight(currentPhoto)}
                  className="w-full py-4 px-6 bg-emerald-950/40 hover:bg-emerald-900/40 border border-emerald-500/30 rounded-xl flex items-center justify-center gap-3 text-emerald-300 font-serif transition-colors group relative overflow-hidden"
                >
                  <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/0 via-emerald-500/10 to-emerald-500/0 -translate-x-[100%] group-hover:translate-x-[100%] transition-transform duration-1000"></div>
                  <Sparkles className="w-5 h-5 text-emerald-400 group-hover:scale-110 transition-transform" />
                  <span>この写真の素晴らしいポイントは？</span>
                </button>
              ) : (
                <div className="bg-emerald-950/60 border border-emerald-500/40 rounded-xl p-5 relative overflow-hidden">
                  <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                    <Sparkles className="w-24 h-24 text-emerald-300" />
                  </div>
                  <h3 className="text-sm font-bold text-emerald-300 flex items-center gap-2 mb-3">
                    <Sparkles className="w-4 h-4" /> 
                    AI 撮影アナリシス
                  </h3>
                  {isAiLoading ? (
                    <div className="flex items-center gap-3 text-emerald-400/80 text-sm font-serif p-2">
                       <Loader2 className="w-4 h-4 animate-spin" />
                       <span>写真の構図と露光データを分析中...</span>
                    </div>
                  ) : (
                    <p className="text-sm text-emerald-50/90 leading-relaxed font-serif relative z-10 whitespace-pre-wrap">
                      {aiInsight}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="text-xs text-gray-500 font-mono flex items-center justify-center mt-6 pt-4 border-t border-white/5 opacity-80">
              {currentIndex + 1} / {validPhotos.length}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
