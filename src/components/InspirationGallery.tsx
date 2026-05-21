import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { MapPin, Calendar, Camera, ChevronLeft, ChevronRight, Loader2, Map as MapIcon, Maximize2 } from "lucide-react";
import { collection, query, where, limit, orderBy, getDocs } from "firebase/firestore"; // getDocsに変更（キャッシュ活用）
import { db } from "../firebase";
import FullScreenGallery from "./FullScreenGallery";

interface ContestPhoto {
  id?: string;
  dNumb?: string;
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
  Camera?: string;
  Lens?: string;
  Exposure?: string;
  [key: string]: any;
}

interface InspirationGalleryProps {
  currentMonth: number;
  currentPrefecture: string;
}

export default function InspirationGallery({ currentMonth, currentPrefecture }: InspirationGalleryProps) {
  const [photos, setPhotos] = useState<ContestPhoto[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [showFullScreen, setShowFullScreen] = useState(false);

  // Auto-play feature
  useEffect(() => {
    if (photos.length <= 1 || showFullScreen) return;
    const timer = setInterval(() => {
      setCurrentIndex((prev) => (prev + 1) % photos.length);
    }, 5000);
    return () => clearInterval(timer);
  }, [photos.length, showFullScreen]);

  useEffect(() => {
    const loadData = async () => {
      try {
        setIsLoading(true);
        
        const cleanPref = currentPrefecture.replace(/[都道府県]$/, "");
        const prefWithSuffix = currentPrefecture; // "長野県" etc.

        // DBに文字列と数値が混在、またはインデックス未構築に備えて全方位でフォールバック
        const monthStr = currentMonth.toString();
        const monthZero = monthStr.padStart(2, "0");
        const monthNum = currentMonth;
        const monthVariants = [monthStr, monthZero, monthNum];

        // 究極のフォールバック (無条件10件限定)
        let docs: any[] = [];
        try {
          const snap = await getDocs(query(collection(db, "contests"), limit(10)));
          docs = snap.docs;
          console.log("🔥 Loaded generic fallback docs count:", docs.length);
        } catch (e) {
          console.error("🔥 Error loading generic fallback docs:", e);
        }

        const mParams = docs.map(doc => {
          const p = doc.data() as ContestPhoto;
          const published = p.Published?.trim();
          const picFileName = p.PicFileName?.trim();
          
          if (!published || !picFileName) return null;

          const year = published.substring(0, 4);
          const customUrl = `https://fupc.photo/PicsDB/PicsDB4Search/${year}/${published}/${picFileName}`.replace(/\/\/+/g, '/').replace('https:/', 'https://');
          
          return { ...p, id: doc.id, generatedImageUrl: customUrl } as ContestPhoto;
        }).filter((p): p is ContestPhoto => p !== null);

        setPhotos(mParams);
        setCurrentIndex(0);
      } catch (err) {
        console.error("Firestore Error:", err);
      } finally {
        setIsLoading(false);
      }
    };
    loadData();
  }, [currentMonth, currentPrefecture]);

  const handleNext = () => {
    if (photos.length > 0) setCurrentIndex((prev) => (prev + 1) % photos.length);
  };

  const handlePrev = () => {
    if (photos.length > 0) setCurrentIndex((prev) => (prev - 1 + photos.length) % photos.length);
  };

  if (isLoading) {
    return (
      <div className="w-full h-64 bg-emerald-950/20 rounded-xl border border-emerald-900/50 flex flex-col items-center justify-center relative overflow-hidden">
        <div className="absolute inset-0 bg-emerald-900/10 animate-pulse"></div>
        <Loader2 className="w-8 h-8 text-emerald-800/80 mb-3 animate-spin relative z-10" />
        <p className="text-emerald-700/80 font-serif tracking-widest text-sm relative z-10">現在、アーカイブをスキャン中...</p>
      </div>
    );
  }

  if (photos.length === 0) {
    return null;
  }

  const currentPhoto = photos[currentIndex];

  return (
    <div className="w-full mt-8 mb-12 relative">
      {/* Blurry Background Layer */}
      {currentPhoto && currentPhoto.generatedImageUrl && (
        <div 
          className="absolute -inset-8 z-0 opacity-20 blur-3xl transition-all duration-1000 ease-in-out pointer-events-none"
          style={{ 
            backgroundImage: `url(${currentPhoto.generatedImageUrl})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center'
          }}
        />
      )}

      <div className="relative z-10">
        <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-xl font-serif text-white flex items-center gap-2">
            <Camera className="w-5 h-5 text-emerald-400" />
            Inspiration Gallery
          </h3>
          <p className="text-xs text-emerald-400/70 mt-1 uppercase tracking-wider">
            Firestore 全データスライドショー (無条件表示)
          </p>
        </div>
        <div className="flex gap-2">
          <button 
            onClick={handlePrev}
            className="p-2 rounded-full bg-emerald-900/50 text-emerald-300 hover:bg-emerald-800 hover:text-white transition-colors"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <button 
            onClick={handleNext}
            className="p-2 rounded-full bg-emerald-900/50 text-emerald-300 hover:bg-emerald-800 hover:text-white transition-colors"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </div>

      <div 
        className="relative group rounded-xl overflow-hidden bg-black aspect-[3/2] shadow-2xl ring-1 ring-white/10 cursor-pointer"
        onClick={() => setShowFullScreen(true)}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={currentPhoto.id || currentIndex}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
            className="absolute inset-0 bg-stone-900"
          >
            {currentPhoto.generatedImageUrl && (
              <img 
                src={currentPhoto.generatedImageUrl}
                alt={currentPhoto.Title || "風景写真"}
                className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity duration-700 hover:scale-105"
                referrerPolicy="no-referrer"
                onError={(e) => {
                  const target = e.target as HTMLImageElement;
                  target.style.display = 'none';
                }}
              />
            )}
            <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-500 z-20 pointer-events-none">
              <div className="bg-black/50 backdrop-blur-sm text-white/90 p-4 rounded-full border border-white/20 transform scale-90 group-hover:scale-100 transition-all">
                <Maximize2 className="w-8 h-8" />
              </div>
            </div>
            <div className="absolute inset-x-0 bottom-0 pt-32 pb-6 px-6 md:pb-8 md:px-8 bg-gradient-to-t from-black/90 via-black/40 to-transparent flex flex-col justify-end pointer-events-none">
              <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>
                  <h4 className="text-2xl md:text-3xl font-serif text-white font-bold mb-2 tracking-wide drop-shadow-md">
                    {currentPhoto.Title || "無題"}
                  </h4>
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-gray-300 font-serif">
                    <span className="flex items-center gap-1.5 opacity-90"><MapPin className="w-4 h-4" />{[currentPhoto.Area, currentPhoto.Place].filter(Boolean).join("・")}</span>
                    <span className="flex items-center gap-1.5 opacity-90"><Calendar className="w-4 h-4" />{currentPhoto.Month}月{currentPhoto.Day ? ` ${currentPhoto.Day}日` : ""} 撮影</span>
                    {currentPhoto.Winner4Search && (
                      <span className="flex items-center gap-1.5 text-emerald-400 font-medium">Photographed by {currentPhoto.Winner4Search}</span>
                    )}
                  </div>
                </div>
                
                {currentPhoto.Area && (
                  <a 
                    href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([currentPhoto.Area, currentPhoto.Place].filter(Boolean).join(" "))}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="pointer-events-auto flex-shrink-0 inline-flex items-center justify-center gap-2 px-4 py-2 bg-emerald-600/80 hover:bg-emerald-500 text-white rounded-md text-xs md:text-sm font-bold transition-all duration-300 border border-emerald-500/50 backdrop-blur-sm self-start md:self-end shadow-lg hover:shadow-emerald-900/50 hover:-translate-y-0.5"
                  >
                    <MapIcon className="w-4 h-4" /> この撮影地をマップで探す
                  </a>
                )}
              </div>
            </div>
          </motion.div>
        </AnimatePresence>

        <div className="absolute top-4 right-4 px-3 py-1 bg-black/60 backdrop-blur-md rounded-full text-xs font-mono text-emerald-400/80 border border-white/10">
          {currentIndex + 1} / {photos.length}
        </div>
      </div>
      </div>
      {showFullScreen && (
        <FullScreenGallery
          photos={photos}
          initialIndex={currentIndex}
          onClose={() => setShowFullScreen(false)}
        />
      )}
    </div>
  );
}
