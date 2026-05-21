import React, { useState, useEffect, useCallback, useRef } from "react";
import { db } from "../firebase";
import { collection, onSnapshot, getDocsFromServer, doc } from "firebase/firestore";
import { motion, AnimatePresence } from "motion/react";
import { useNavigate, Link } from "react-router-dom";
import { 
  Sun, Cloud, CloudRain, CloudLightning, Wind, Thermometer, Droplets, 
  Sunrise, Sunset, Moon, MapPin, Search, Calendar, Landmark, Camera,
  BookOpen, ChevronRight, Info, ExternalLink, ArrowLeftRight, Loader2,
  Navigation, RefreshCw, CloudSun, HelpCircle, X, Compass, Clock3, Waves,
  ChevronDown, ChevronUp, AlignLeft, Sparkles
} from "lucide-react";
import SunCalc from "suncalc";
import { getSolarTerm, getMicroSeason } from "../lib/seasonalData";
import { 
  fetchPhotographyHistory, 
  fetchSeasonalNews, 
  fetchWeatherAdvice,
  fetchTideData,
  fetchMarineData,
  fetchCoordinates,
  fetchLocationNameFromCoordinates,
  fetchWeather,
  ReferenceData,
  PhotographyHistoryEvent,
  SeasonalNews,
  WeatherAdvice,
  TideData,
  MarineData
} from "../services/geminiReferenceService";
import InspirationGallery from "./InspirationGallery";

const WeatherIcon = ({ weather, isNight = false, size = 24, className = "" }: { weather: string; isNight?: boolean; size?: number; className?: string }) => {
  if (weather.includes("晴")) return isNight ? <Moon size={size} className={`text-blue-200 ${className}`} /> : <Sun size={size} className={`text-orange-400 ${className}`} />;
  if (weather.includes("雷")) return <CloudLightning size={size} className={`text-yellow-600 ${className}`} />;
  if (weather.includes("雨")) return <CloudRain size={size} className={`text-blue-500 ${className}`} />;
  if (weather.includes("曇")) return <Cloud size={size} className={`text-stone-500 font-bold ${className}`} />;
  return isNight ? <Moon size={size} className={`text-blue-200 ${className}`} /> : <CloudSun size={size} className={`text-stone-500 ${className}`} />;
};

function getLunarDetails(phase: number) {
  const lunarAge = phase * 29.53;
  const ageInt = Math.round(lunarAge);

  let moonName = "";
  if (ageInt === 0 || ageInt === 29 || ageInt === 30) moonName = "新月";
  else if (ageInt >= 1 && ageInt <= 3) moonName = "三日月";
  else if (ageInt >= 4 && ageInt <= 6) moonName = "夕月";
  else if (ageInt === 7 || ageInt === 8) moonName = "上弦の月";
  else if (ageInt >= 9 && ageInt <= 12) moonName = "十三夜";
  else if (ageInt >= 13 && ageInt <= 16) moonName = "満月 (望月)";
  else if (ageInt >= 17 && ageInt <= 19) moonName = "立待月・居待月";
  else if (ageInt === 20 || ageInt === 21) moonName = "更待月";
  else if (ageInt === 22 || ageInt === 23) moonName = "下弦の月";
  else if (ageInt >= 24 && ageInt <= 28) moonName = "有明の月";
  else moonName = "月";

  let tideName = "";
  if ([0, 1, 2, 14, 15, 16, 17, 29, 30].includes(ageInt)) tideName = "大潮";
  else if ([3, 4, 5, 6, 12, 13, 18, 19, 20, 21, 27, 28].includes(ageInt)) tideName = "中潮";
  else if ([7, 8, 9, 22, 23, 24].includes(ageInt)) tideName = "小潮";
  else if ([10, 25].includes(ageInt)) tideName = "長潮";
  else if ([11, 26].includes(ageInt)) tideName = "若潮";

  return { lunarAge: lunarAge.toFixed(1), moonName, tideName };
}

const MoonIllustration = ({ phase }: { phase: number }) => {
  const normalizedPhase = phase % 1;
  const rightLight = normalizedPhase <= 0.5;
  const ellipseLight = (normalizedPhase > 0.25 && normalizedPhase < 0.75);
  const scaleX = Math.abs(Math.cos(normalizedPhase * Math.PI * 2));

  return (
    <div className="w-16 h-16 rounded-full relative overflow-hidden border border-white/20 shadow-[0_0_15px_rgba(255,255,255,0.1)] block mx-auto" style={{ backgroundColor: '#0f172a' }}>
      <div 
        className="absolute inset-0" 
        style={{ 
          background: rightLight 
            ? 'linear-gradient(to right, #0f172a 50%, #fef08a 50%)' 
            : 'linear-gradient(to right, #fef08a 50%, #0f172a 50%)' 
        }} 
      />
      <div 
        className="absolute top-0 bottom-0 left-0 right-0 rounded-full" 
        style={{ 
          background: ellipseLight ? '#fef08a' : '#0f172a', 
          transform: `scaleX(${scaleX})` 
        }} 
      />
      <div className="absolute inset-0 rounded-full shadow-[inset_-6px_-6px_20px_rgba(0,0,0,0.6)] pointer-events-none" />
    </div>
  );
};

const SimpleCompass = ({ angle, label }: { angle: number; label: string }) => {
  return (
    <div className="flex flex-col items-center gap-2 group cursor-pointer transition-transform hover:scale-105">
      <div className="relative w-16 h-16 rounded-full border-2 border-emerald-700/30 flex items-center justify-center bg-white/5 shadow-inner">
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-[1px] h-full bg-emerald-500/10" />
          <div className="h-[1px] w-full bg-emerald-500/10" />
        </div>
        <div className="absolute top-1 text-[8px] font-bold text-emerald-500/40">N</div>
        <motion.div 
          style={{ rotate: angle }}
          className="relative z-10"
        >
          <Navigation className="w-6 h-6 text-emerald-400 fill-emerald-400/20" />
        </motion.div>
      </div>
      <div className="text-center">
        <span className="text-xs font-bold text-emerald-300 block uppercase tracking-tighter">{label}</span>
        <span className="text-xs font-bold text-white">{getCompassDirection(angle)}</span>
      </div>
    </div>
  );
};

const getCompassDirection = (deg: number) => {
  const directions = ['北', '北北東', '北東', '東北東', '東', '東南東', '南東', '南南東', '南', '南南西', '南西', '西南西', '西', '西北西', '北西', '北北西'];
  const index = Math.round(deg / 22.5) % 16;
  return directions[index < 0 ? index + 16 : index];
};

const AstroDetailModal = React.memo(({ 
  type, 
  time, 
  angle,
  isTomorrow,
  locationName,
  selectedDate,
  onClose,
  onOpenGuide
}: { 
  type: 'sunrise' | 'sunset' | 'moonrise' | 'moonset'; 
  time: Date | null; 
  angle: number; 
  isTomorrow?: boolean;
  locationName: string;
  selectedDate: Date;
  onClose: () => void;
  onOpenGuide: () => void;
}) => {
  const [timeLeft, setTimeLeft] = useState("");
  const [deviceHeading, setDeviceHeading] = useState<number>(0);
  const handleOrientationRef = useRef<((event: DeviceOrientationEvent) => void) | null>(null);
  
  useEffect(() => {
    if (!time) return;
    const timer = setInterval(() => {
      const now = new Date();
      const diff = time.getTime() - now.getTime();
      if (diff < 0) {
        setTimeLeft("00:00:00");
        return;
      }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setTimeLeft(`${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`);
    }, 1000);
    return () => clearInterval(timer);
  }, [time]);

  useEffect(() => {
    const handleOrientation = (event: DeviceOrientationEvent) => {
      let heading = (event as any).webkitCompassHeading;
      if (heading === undefined || heading === null) {
        if (typeof event.alpha === 'number') {
          heading = 360 - event.alpha;
        }
      }
      if (typeof heading === 'number' && !isNaN(heading)) {
        setDeviceHeading(heading);
      }
    };
    handleOrientationRef.current = handleOrientation;

    if (typeof window !== "undefined" && window.DeviceOrientationEvent) {
      window.addEventListener("deviceorientationabsolute", handleOrientation as any, true);
      window.addEventListener("deviceorientation", handleOrientation as any, true);
    }
    return () => {
      if (typeof window !== "undefined") {
         window.removeEventListener("deviceorientationabsolute", handleOrientation as any, true);
         window.removeEventListener("deviceorientation", handleOrientation as any, true);
      }
    };
  }, []);

  const requestCompassPermission = async () => {
    if (typeof (DeviceOrientationEvent as any) !== 'undefined' && typeof (DeviceOrientationEvent as any).requestPermission === 'function') {
      try {
        const permission = await (DeviceOrientationEvent as any).requestPermission();
        if (permission === 'granted' && handleOrientationRef.current) {
          // Re-attach listener after permission is granted
          window.removeEventListener("deviceorientationabsolute", handleOrientationRef.current as any, true);
          window.removeEventListener("deviceorientation", handleOrientationRef.current as any, true);
          window.addEventListener("deviceorientationabsolute", handleOrientationRef.current as any, true);
          window.addEventListener("deviceorientation", handleOrientationRef.current as any, true);
        }
      } catch (error) {
        console.error("Compass permission error:", error);
      }
    }
  };

  const labels = {
    sunrise: "日の出",
    sunset: "日の入",
    moonrise: "月の出",
    moonset: "月の入"
  };

  const Icons = {
    sunrise: Sunrise,
    sunset: Sunset,
    moonrise: Moon,
    moonset: Moon
  };

  const ActiveIcon = Icons[type];

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[110] flex items-center justify-center p-6 bg-emerald-950/90 backdrop-blur-md"
      onClick={onClose}
    >
      <motion.div 
        initial={{ scale: 0.9, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        className="bg-emerald-900 border border-emerald-700/50 p-8 rounded-sm max-w-sm w-full text-center shadow-2xl relative"
        onClick={e => e.stopPropagation()}
      >
        <button onClick={onClose} className="absolute top-4 right-4 text-emerald-400/50 hover:text-white transition-colors p-2">
          <X className="w-6 h-6" />
        </button>

        <button 
          onClick={() => { onClose(); onOpenGuide(); }} 
          className="absolute top-4 left-4 text-emerald-300 hover:text-white transition-colors p-2 flex items-center gap-1 bg-emerald-800/40 rounded-full"
        >
          <HelpCircle className="w-5 h-5" />
        </button>
        
        <ActiveIcon className="w-16 h-16 text-emerald-400 mx-auto mb-6" />
        <h2 className="text-3xl font-serif text-white mb-2">{labels[type]} 詳細情報</h2>
        <div className="mb-8">
          <p className="text-base text-emerald-400/90 mb-2 font-serif flex items-center justify-center flex-wrap gap-2">
            <span>{locationName} - {time ? time.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" }) : selectedDate.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" })}</span>
            {isTomorrow && <span className="text-sm font-sans font-bold text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded-full border border-amber-400/20">明日</span>}
          </p>
          <p className="text-emerald-300 font-bold text-2xl">{time?.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) || "--:--:--"}</p>
        </div>

        <div className="flex flex-col items-center gap-6 mb-10" onClick={requestCompassPermission}>
          <div className="relative w-48 h-48 rounded-full flex items-center justify-center">
            {/* Compass Container (rotates based on device heading so North aligns correctly) */}
            <motion.div 
              style={{ rotate: -deviceHeading }}
              className="absolute inset-0 rounded-full border-4 border-emerald-800 flex items-center justify-center bg-emerald-950"
            >
              <div className="absolute inset-4 border border-emerald-800/30 rounded-full" />
              <div className="absolute top-2 font-bold text-emerald-500 text-sm">北 (N)</div>
              <div className="absolute bottom-2 font-bold text-emerald-800 text-sm text-opacity-80">南 (S)</div>
              <div className="absolute left-2 font-bold text-emerald-800 text-sm text-opacity-80">西 (W)</div>
              <div className="absolute right-2 font-bold text-emerald-800 text-sm text-opacity-80">東 (E)</div>
              
              <Compass className="w-16 h-16 text-emerald-500/30 relative z-0" />
              
              {/* The Needle/Line pointing to the Sun/Moon */}
              <motion.div 
                style={{ rotate: angle }}
                className="absolute inset-0 flex items-center justify-center pointer-events-none"
              >
                <div className="w-1 h-24 bg-gradient-to-t from-transparent via-emerald-400 to-emerald-400 absolute bottom-1/2 rounded-full shadow-[0_0_15px_rgba(52,211,153,0.8)]" />
                
                {/* Sun/Moon Icon at the tip of the line, outside the compass! */}
                <div className="absolute top-0 -translate-y-6">
                  <ActiveIcon className="w-8 h-8 text-emerald-200 drop-shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
                </div>
              </motion.div>
            </motion.div>
          </div>
          <div className="text-center mt-4">
            <p className="text-sm text-emerald-400 font-bold uppercase mb-1">方位角</p>
            <p className="text-3xl font-serif text-white">{getCompassDirection(angle)} <span className="text-lg font-mono opacity-80">{Math.round(angle)}°</span></p>
            {typeof (DeviceOrientationEvent as any) !== 'undefined' && typeof (DeviceOrientationEvent as any).requestPermission === 'function' && (
              <p className="text-xs text-emerald-500/70 mt-2">※コンパスを正しく向けるにはタップして許可</p>
            )}
          </div>
        </div>

        <div className="bg-emerald-950/80 p-6 rounded border border-emerald-800">
          <p className="text-xs font-bold text-emerald-300 uppercase tracking-widest mb-3">その瞬間まで (カウントダウン)</p>
          <div className="text-4xl font-mono text-emerald-400 tracking-wider font-bold">
            {timeLeft || "--:--:--"}
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
});

const galleriesByRegion: Record<string, {name: string, access: string, url: string}[]> = {
  "東京": [
    { name: "富士フイルムフォトサロン 東京", access: "六本木", url: "https://fujifilmsquare.jp/" },
    { name: "キヤノンギャラリー S ／キヤノンオープンギャラリー1・2", access: "品川", url: "https://personal.canon.jp/showroom/gallery/shinagawa" },
    { name: "キヤノンギャラリー銀座", access: "銀座", url: "https://personal.canon.jp/showroom/gallery/ginza" },
    { name: "ソニーイメージングギャラリー銀座", access: "銀座", url: "https://www.sony.jp/camera/imaging-gallery/" },
    { name: "ニコンプラザ東京 THE GALLERY", access: "新宿", url: "https://nij.nikon.com/enjoy/nikonplaza/tokyo/#tokyo01" },
    { name: "富士フォトギャラリー銀座", access: "銀座", url: "https://www.prolab-create.jp/gallery/ginza/" },
    { name: "ＯＭシステムギャラリー", access: "西新宿", url: "https://note.com/omsystem_plaza" },
    { name: "東京都写真美術館", access: "恵比寿", url: "https://topmuseum.jp/" },
    { name: "Nine Gallery", access: "外苑前", url: "https://ninegallery.com/" },
  ],
  "札幌": [
    { name: "富士フイルムフォトサロン 札幌", access: "大通", url: "https://www.fujifilm.co.jp/photosalon/sapporo/" },
    { name: "αプラザ札幌ギャラリー", access: "大通", url: "https://www.sony.jp/ichigan/plaza/sapporo/" },
  ],
  "名古屋": [
    { name: "富士フイルムフォトサロン 名古屋", access: "伏見", url: "https://www.fujifilm.co.jp/photosalon/nagoya/" },
    { name: "αプラザ名古屋ギャラリー", access: "栄", url: "https://www.sony.jp/ichigan/plaza/nagoya/" },
  ],
  "大阪": [
    { name: "富士フイルムフォトサロン 大阪", access: "本町", url: "https://www.fujifilm.co.jp/photosalon/osaka/" },
    { name: "キヤノンギャラリー大阪", access: "中之島", url: "https://personal.canon.jp/showroom/gallery/osaka" },
    { name: "αプラザ大阪ギャラリー", access: "梅田", url: "https://www.sony.jp/store/retail/osaka/" },
    { name: "ニコンプラザ大阪 THE GALLERY", access: "本町", url: "https://nij.nikon.com/enjoy/nikonplaza/osaka/#osaka01" },
  ],
  "福岡": [
    { name: "αプラザ福岡天神ギャラリー", access: "天神", url: "https://www.sony.jp/ichigan/plaza/fukuoka-tenjin/" },
  ],
  "その他": [
    { name: "土門拳記念館", access: "山形県酒田市", url: "http://www.domonken-kinenkan.jp/" },
    { name: "奈良市写真美術館", access: "奈良市", url: "http://irietaikichi.jp/" },
    { name: "ミュゼふくおかカメラ館", access: "富山県高岡市", url: "http://www.camerakan.com/" },
  ]
};

const paperSizes = [
  { size: "L判", dimensions: "89 × 127 mm" },
  { size: "2L判", dimensions: "127 × 178 mm" },
  { size: "六切", dimensions: "203 × 254 mm" },
  { size: "四切", dimensions: "254 × 305 mm" },
  { size: "A4", dimensions: "210 × 297 mm" },
  { size: "A3", dimensions: "297 × 420 mm" },
  { size: "半切", dimensions: "356 × 432 mm" },
  { size: "全紙", dimensions: "457 × 560 mm" },
];

const AILoadingState = ({ label }: { label: string }) => (
  <div className="flex flex-col items-center justify-center py-10 px-4 space-y-4 bg-stone-50/30 rounded-sm border border-dashed border-emerald-900/10">
    <div className="relative">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
        className="text-emerald-800 opacity-70"
      >
        <RefreshCw className="w-8 h-8 md:w-10 md:h-10 stroke-[1.5]" />
      </motion.div>
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="w-1 h-1 bg-emerald-800 rounded-full" />
      </div>
    </div>
    <div className="text-center">
      <div className="text-sm md:text-xs font-bold text-emerald-900 tracking-[0.3em] uppercase mb-1">
        Now Loading...
      </div>
      <div className="text-[9px] text-stone-500 font-bold font-medium tracking-wider">
        {label}を取得中
      </div>
    </div>
  </div>
);

const LOCATION_MASTER: Record<string, { Notes: string }> = {
  "あやめ公園池": { Notes: "シラカバ水鏡" },
  "荒船海岸": { Notes: "潮の干満に注意" },
  "美瑛": { Notes: "冬期封鎖、私有地のため立ち入り禁止エリアあり" },
  "知床": { Notes: "ヒル・クマ対策必須" }
};

const ReferencePage = () => {
  const navigate = useNavigate();
  const [now, setNow] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [locationInput, setLocationInput] = useState("東京");
  const [locationName, setLocationName] = useState("東京");
  const [coord, setCoord] = useState<{ lat: number; lng: number; elevation?: number }>({ lat: 35.6895, lng: 139.6917 });
  const [isLoading, setIsLoading] = useState(true);
  
  const requestCountRef = useRef<number>(0);
  
  // AI Derived States
  const [historyEvents, setHistoryEvents] = useState<PhotographyHistoryEvent[]>([]);
  const [seasonalNews, setSeasonalNews] = useState<SeasonalNews[]>([]);
  const [tideData, setTideData] = useState<TideData | null>(null);
  const [marineData, setMarineData] = useState<MarineData | null>(null);
  const [weatherData, setWeatherData] = useState<ReferenceData['weather'] | null>(null);
  const [isGuideOpen, setIsGuideOpen] = useState(false);
  const [activeAstro, setActiveAstro] = useState<{ type: 'sunrise' | 'sunset' | 'moonrise' | 'moonset'; time: Date | null; angle: number; isTomorrow?: boolean } | null>(null);

  // Tochikan Logic
  const notes = Object.entries(LOCATION_MASTER).find(([key]) => locationName.includes(key))?.[1]?.Notes || "";
  
  const hasSurvivalWarning = ["冬期封鎖", "ヒル・クマ対策", "私有地", "立ち入り禁止"].some(kw => notes.includes(kw));
  const survivalWarningText = hasSurvivalWarning ? `【プロ直伝トチカン情報】 ${notes}` : null;
  
  // Simulate wind logic
  const weatherTranslation = (weatherData && notes.includes("水鏡"))
    ? "💡トチカン連動：水鏡の成立確率大。夜明け直後を狙ってください。" : null;

  const tideStrategy = (notes.includes("潮の干満に注意"))
    ? "⌛タイドグラフ攻略ヒント：干潮時間の前後2時間のみが物理的なアプローチ限界です。満ちる前に撤収ルートの確保を。" : null;

  const handleAISummaryClick = () => {
    // Generate dataToSummarize block
    let dataString = `【気象状況】\n`;
    if (weatherData) {
      dataString += `概況: ${weatherData.summary}\n最高降水確率: ${weatherData.precipitationProb}\n`;
    }
    dataString += `\n【自然・旬の情報】\n`;
    seasonalNews.forEach(n => dataString += `- ${n.headline} (${n.location}, ${n.date})\n`);
    dataString += `\n【写真界の今日】\n`;
    historyEvents.forEach(h => dataString += `- ${h.event}\n`);

    navigate('/reference/summary', {
      state: {
        locationName,
        selectedDate: selectedDate.toISOString(),
        dataToSummarize: dataString
      }
    });
  };

  const updateData = useCallback(async (loc: string, date: Date, overrideCoord?: { lat: number; lng: number; elevation?: number }) => {
    const currentRequestId = Date.now();
    requestCountRef.current = currentRequestId;
    setIsLoading(true);
    
    // Clear previous data
    setHistoryEvents([]);
    setSeasonalNews([]);
    setTideData(null);
    setMarineData(null);
    setWeatherData(null);

    try {
      let coordData = overrideCoord;
      if (!coordData) {
        coordData = await fetchCoordinates(loc);
      }
      
      if (requestCountRef.current !== currentRequestId) return;

      if (coordData) {
        setCoord(coordData);
        setLocationName(loc);
      } else {
        const cityCoords: Record<string, {lat: number, lng: number, elevation: number}> = {
          "東京": { lat: 35.6895, lng: 139.6917, elevation: 40 },
          "福岡": { lat: 33.5902, lng: 130.4017, elevation: 3 },
          "札幌": { lat: 43.0618, lng: 141.3545, elevation: 26 },
          "京都": { lat: 35.0116, lng: 135.7681, elevation: 43 },
        };
        if (cityCoords[loc]) setCoord(cityCoords[loc]);
      }

      // Fetch AI Components
      const loadHistory = fetchPhotographyHistory(date).then(data => {
        if (requestCountRef.current === currentRequestId) setHistoryEvents(data);
      });
      
      const loadNews = fetchSeasonalNews(loc).then(data => {
        if (requestCountRef.current === currentRequestId) setSeasonalNews(data);
      });

      const loadWeatherDetail = fetchWeather(loc, date, coordData || coord).then(async data => {
        if (requestCountRef.current === currentRequestId) {
          setWeatherData(data);
        }
      });

      const loadTides = fetchTideData(loc, date, coordData || coord).then(data => {
        if (requestCountRef.current === currentRequestId) setTideData(data);
      });

      const loadMarine = fetchMarineData(loc, date, coordData || coord).then(data => {
        if (requestCountRef.current === currentRequestId) setMarineData(data);
      });

      await Promise.allSettled([loadHistory, loadNews, loadTides, loadMarine, loadWeatherDetail]);

    } catch (error) {
      console.error("Data update error:", error);
    } finally {
      if (requestCountRef.current === currentRequestId) {
        setIsLoading(false);
      }
    }
  }, []);

  // Fetch default location from general settings
  useEffect(() => {
    const unsub = onSnapshot(doc(db, "settings", "general"), (snapshot) => {
      if (snapshot.exists()) {
        const data = snapshot.data();
        if (data.refLocation && locationName === "東京" && locationInput === "東京") {
          setLocationName(data.refLocation);
          setLocationInput(data.refLocation);
          updateData(data.refLocation, selectedDate);
        }
      }
    }, (error) => console.error("General Settings onSnapshot error:", error));
    return unsub;
  }, [updateData, selectedDate, locationName, locationInput]);

  // Clock
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Initial Load & Geolocation
  useEffect(() => {
    let active = true;
    const timeoutId = setTimeout(() => {
      if (active) {
        updateData("東京", new Date());
      }
    }, 6000); // 6 seconds fallback

    const init = async () => {
      if ("geolocation" in navigator) {
        navigator.geolocation.getCurrentPosition(
          async (pos) => {
            if (!active) return;
            clearTimeout(timeoutId);
            const coords = { 
              lat: pos.coords.latitude, 
              lng: pos.coords.longitude,
              ...(pos.coords.altitude !== null ? { elevation: Math.round(pos.coords.altitude) } : {}) 
            };
            setCoord(coords);
            try {
              const fetchedName = await fetchLocationNameFromCoordinates(coords.lat, coords.lng);
              const locName = fetchedName !== "現在地" ? fetchedName : "東京";
              setLocationName(locName);
              setLocationInput(locName);
              updateData(locName, new Date(), coords);
            } catch (error) {
              const locName = "東京";
              setLocationName(locName);
              setLocationInput(locName);
              updateData(locName, new Date(), coords);
            }
          },
          () => {
            if (!active) return;
            clearTimeout(timeoutId);
            updateData("東京", new Date());
          },
          { timeout: 10000, enableHighAccuracy: false }
        );
      } else {
        clearTimeout(timeoutId);
        updateData("東京", new Date());
      }
    };
    init();
    return () => {
      active = false;
      clearTimeout(timeoutId);
    };
  }, [updateData]);

  const isSameDay = (d1: Date, d2: Date) => 
    d1.getFullYear() === d2.getFullYear() &&
    d1.getMonth() === d2.getMonth() &&
    d1.getDate() === d2.getDate();

  const getAstroData = (eventType: 'sunrise' | 'sunset' | 'moonrise' | 'moonset') => {
    const isTodayDate = isSameDay(selectedDate, new Date());
    const now = new Date();
    
    let times: any;
    let time: Date | null | undefined;
    let isTomorrow = false;
    let baseDate = new Date(selectedDate);
  
    if (eventType === 'sunrise' || eventType === 'sunset') {
      times = SunCalc.getTimes(baseDate, coord.lat, coord.lng);
      time = times[eventType];
    } else {
      times = SunCalc.getMoonTimes(baseDate, coord.lat, coord.lng);
      time = eventType === 'moonrise' ? times.rise : times.set;
    }
  
    if (isTodayDate) {
      if ((time && time < now) || (!time && eventType.startsWith('moon'))) {
          isTomorrow = true;
          baseDate.setDate(baseDate.getDate() + 1);
          if (eventType === 'sunrise' || eventType === 'sunset') {
            times = SunCalc.getTimes(baseDate, coord.lat, coord.lng);
            time = times[eventType];
          } else {
            times = SunCalc.getMoonTimes(baseDate, coord.lat, coord.lng);
            time = eventType === 'moonrise' ? times.rise : times.set;
          }
      }
    }
  
    let angle = 0;
    if (time) {
      const pos = (eventType === 'sunrise' || eventType === 'sunset')
        ? SunCalc.getPosition(time, coord.lat, coord.lng)
        : SunCalc.getMoonPosition(time, coord.lat, coord.lng);
      angle = (pos.azimuth * 180 / Math.PI + 180) % 360;
    }
  
    return { time: time || null, isTomorrow, angle };
  };

  const currentSunTimes = SunCalc.getTimes(new Date(), coord.lat, coord.lng);
  const isCurrentlyNight = new Date() < currentSunTimes.sunrise || new Date() > currentSunTimes.sunset;

  const sunriseData = getAstroData('sunrise');
  const sunsetData = getAstroData('sunset');
  const moonriseData = getAstroData('moonrise');
  const moonsetData = getAstroData('moonset');
  const moonIllum = SunCalc.getMoonIllumination(selectedDate);
  
  const allAstroEvents = [
    { type: 'sunrise', data: sunriseData, label: '日の出時刻' },
    { type: 'sunset', data: sunsetData, label: '日の入時刻' },
    { type: 'moonrise', data: moonriseData, label: '月の出時刻' },
    { type: 'moonset', data: moonsetData, label: '月の入時刻' },
  ].sort((a, b) => {
    const timeA = a.data.time ? a.data.time.getTime() : Infinity;
    const timeB = b.data.time ? b.data.time.getTime() : Infinity;
    return timeA - timeB;
  });

  const solarTerm = getSolarTerm(selectedDate);
  const microSeason = getMicroSeason(selectedDate);

  const handleAstroClose = useCallback(() => setActiveAstro(null), []);
  const handleOpenGuide = useCallback(() => setIsGuideOpen(true), []);

  return (
    <div className="min-h-screen bg-stone-50 pt-24 pb-12 md:pt-32 md:pb-24 font-sans text-emerald-950">
      <AnimatePresence>
        {activeAstro && (
          <AstroDetailModal 
            {...activeAstro} 
            locationName={locationName}
            selectedDate={selectedDate}
            onClose={handleAstroClose} 
            onOpenGuide={handleOpenGuide}
          />
        )}
      </AnimatePresence>
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <header className="mb-10 md:mb-12 border-b border-emerald-900/10 pb-8 md:pb-12">
          <div className="text-left">
            <h1 className="text-4xl md:text-5xl font-serif mb-4 md:mb-5 tracking-tight">風景写真AIリファレンス</h1>
            <p className="text-stone-600 text-base md:text-lg font-medium">撮影地に即した気象・天文・季節情報をAIが解析します。</p>
            <p className="text-xs md:text-sm text-stone-500 font-bold mt-3 font-medium">※すべての情報が表示されるまで時間がかかる場合があります。</p>
          </div>
        </header>

        <div className="grid lg:grid-cols-3 gap-8 md:gap-12">
          {/* Main Info Column */}
          <div className="lg:col-span-2 space-y-8 md:space-y-12">
            
            {/* Today's Section */}
            <section className="bg-emerald-900 text-white rounded-sm p-8 md:p-12 relative overflow-hidden shadow-2xl">
              <div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none hidden md:block">
                <Sun className="w-64 h-64" />
              </div>
              
              <div className="relative z-10">
                <div className="flex flex-col sm:flex-row justify-between sm:items-end gap-8 mb-12 border-b border-white/10 pb-10">
                  <div className="flex-grow flex flex-row flex-wrap items-end gap-x-6 gap-y-3 md:gap-8">
                    <div>
                      <h2 className="text-base md:text-lg font-serif mb-2 md:mb-3 text-emerald-300">【今日も風景写真日和】</h2>
                      <span className="text-3xl md:text-4xl font-serif leading-tight">
                        {selectedDate.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric", weekday: "short" })}
                      </span>
                    </div>
                    {selectedDate.toDateString() === now.toDateString() && (
                      <div className="flex flex-col items-end sm:items-start md:items-end bg-black/20 p-3 md:p-4 rounded-sm border border-emerald-500/20 shadow-inner">
                        <span className="text-[10px] sm:text-xs font-bold text-emerald-400/90 tracking-widest uppercase mb-1.5 flex items-center gap-1.5">
                          <Clock3 className="w-3.5 h-3.5" /> 撮影基準時間
                        </span>
                        <span className="text-2xl md:text-4xl font-mono opacity-100 text-white whitespace-nowrap leading-none tracking-tight">
                          {now.toLocaleTimeString("ja-JP", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="bg-white/10 p-4 md:p-3 rounded-sm border border-white/5 backdrop-blur-sm w-full sm:w-auto self-start lg:self-auto">
                    <div className="flex flex-wrap items-center gap-3 md:gap-3">
                      <div className="flex items-center gap-2 px-3 py-2 bg-emerald-950/50 rounded-sm border border-white/10 flex-grow sm:flex-grow-0">
                        <MapPin className="w-4 h-4 text-emerald-400" />
                        <input 
                          type="text" 
                          value={locationInput}
                          onChange={(e) => setLocationInput(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && updateData(locationInput, selectedDate)}
                          className="bg-transparent text-base md:text-sm font-bold outline-none w-full sm:w-28 text-white placeholder:text-white/70"
                          placeholder="地名を検索..."
                        />
                      </div>
                      <div className="flex items-center gap-2 px-3 py-2 bg-emerald-950/50 rounded-sm border border-white/10 flex-grow sm:flex-grow-0">
                        <Calendar className="w-5 h-5 text-emerald-400" />
                        <input 
                          type="date" 
                          value={selectedDate.toISOString().split('T')[0]}
                          onChange={(e) => {
                            const newDate = new Date(e.target.value);
                            setSelectedDate(newDate);
                            updateData(locationName, newDate);
                          }}
                          className="bg-transparent text-base md:text-sm font-bold outline-none text-white w-full sm:w-auto appearance-none"
                          style={{ colorScheme: 'dark' }}
                        />
                      </div>
                      <div className="flex items-center gap-2 mt-3 sm:mt-0 ml-auto sm:ml-0">
                        <button 
                          onClick={handleAISummaryClick}
                          disabled={isLoading}
                          className="bg-emerald-900 border border-emerald-500/50 text-emerald-300 p-3 md:p-2 rounded-sm hover:bg-emerald-800 transition-colors disabled:opacity-80 flex items-center gap-2 font-bold text-sm"
                          title="現在の結果からAIサマリーを生成する"
                        >
                          <Sparkles className="w-4 h-4 text-amber-400" />
                          <span className="hidden sm:inline">AIサマリー</span>
                        </button>
                        <button 
                          onClick={() => updateData(locationInput, selectedDate)}
                          disabled={isLoading}
                          className="bg-emerald-500 text-emerald-950 p-3 md:p-2 rounded-sm hover:bg-emerald-400 transition-colors disabled:opacity-80 flex-none"
                          title="情報を更新"
                        >
                          {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <RefreshCw className="w-5 h-5 md:w-4 md:h-4" />}
                        </button>
                      </div>
                    </div>
                    <div className="mt-3 text-right">
                      <button 
                        onClick={() => setIsGuideOpen(true)}
                        className="text-sm md:text-xs text-emerald-300/80 hover:text-emerald-300 transition-colors flex items-center gap-1.5 ml-auto font-medium"
                      >
                        <HelpCircle className="w-3.5 h-3.5 md:w-2.5 md:h-2.5" /> 【今日も風景写真日和】の使い方
                      </button>
                    </div>
                  </div>
                </div>

                <div className="grid md:grid-cols-2 gap-10 md:gap-12">
                  <div className="space-y-10">
                    <div>
                      <h3 className="text-xl font-bold font-serif text-emerald-300 mb-2 flex items-center gap-3">
                        <AlignLeft className="w-6 h-6" /> 今日の風景
                      </h3>
                      <p className="text-sm text-emerald-300 mb-8 font-serif">{locationName} - {selectedDate.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" })}</p>

                      {hasSurvivalWarning && (
                        <div className="bg-red-950/60 border border-red-500/50 p-4 md:p-5 rounded-sm mb-8 shadow-inner">
                          <span className="inline-block bg-red-600 text-white text-[11px] font-bold px-2 py-1 rounded mb-3 tracking-widest">
                            ⚠️現地サバイバル警告
                          </span>
                          <p className="text-red-100 text-sm leading-relaxed font-bold">
                            {survivalWarningText}
                          </p>
                        </div>
                      )}

                      <h4 className="text-xs font-bold uppercase tracking-[0.3em] text-emerald-300 mb-5 flex items-center gap-2">
                        <Calendar className="w-3 h-3" /> 二十四節気・七十二候
                      </h4>
                      <div className="space-y-8">
                        <div className="group cursor-default">
                          <div className="flex items-baseline gap-4 mb-2">
                            <span className="text-3xl md:text-2xl font-serif">{solarTerm.nameJP}</span>
                            <span className="text-sm md:text-xs opacity-90">（{solarTerm.reading}）</span>
                          </div>
                          <p className="text-base md:text-sm text-emerald-100/90 leading-relaxed font-medium">{solarTerm.description}</p>
                        </div>
                        <div className="group cursor-default">
                          <div className="flex items-baseline gap-4 mb-2">
                            <span className="text-2xl md:text-xl font-serif text-emerald-200">{microSeason.nameJP}</span>
                            <span className="text-sm md:text-xs opacity-90">（{microSeason.reading}）</span>
                          </div>
                          <p className="text-base md:text-sm text-emerald-100/90 leading-relaxed font-medium">{microSeason.description}</p>
                        </div>
                      </div>
                    </div>

                    <InspirationGallery 
                      currentMonth={selectedDate.getMonth() + 1} 
                      currentPrefecture={locationName.split(/[都道府県]/)[0] || ""} 
                    />

                    <div className="bg-white/5 border border-white/10 p-6 md:p-8 rounded-sm">
                      <h4 className="text-lg font-serif font-bold text-emerald-300 mb-2 flex items-center gap-3">
                        <CloudSun className="w-6 h-6" /> 今日の天気
                      </h4>
                      <p className="text-sm text-emerald-300 mb-4 font-serif">{locationName} - {selectedDate.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" })}</p>
                      {isLoading ? (
                        <AILoadingState label="気象詳細" />
                      ) : weatherData ? (
                        <div className="space-y-8">
                          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-6 px-1 bg-white/5 p-4 rounded border border-white/10">
                            <div className="flex items-center gap-4">
                              <WeatherIcon weather={weatherData.summary} isNight={isCurrentlyNight} size={48} />
                              <span className="text-2xl font-bold leading-tight">
                                {weatherData.summary}
                              </span>
                            </div>
                            <div className="text-right">
                              <span className="text-xs font-bold text-emerald-400 block mb-1 uppercase tracking-widest">降水確率</span>
                              <span className="text-3xl font-serif font-bold text-white whitespace-nowrap">
                                {weatherData.precipitationProb}
                              </span>
                            </div>
                          </div>
                          
                          <div className="space-y-4">
                            <h5 className="text-xs font-bold text-emerald-500 uppercase tracking-widest flex items-center gap-2">
                              <Clock3 className="w-3 h-3" /> 1日の推移
                            </h5>
                            <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 sm:gap-2 pt-1">
                              {weatherData.hourly.map((h, i) => {
                                const hourStr = h.time.split(':')[0];
                                const hour = parseInt(hourStr, 10);
                                const sunriseH = currentSunTimes.sunrise.getHours();
                                const sunsetH = currentSunTimes.sunset.getHours();
                                const isHourNight = hour <= sunriseH || hour >= sunsetH;
                                return (
                                  <div key={i} className="text-center group bg-white/5 p-3 rounded hover:bg-white/10 transition-colors border border-white/5">
                                    <div className="text-xs font-mono opacity-80 mb-3 group-hover:opacity-100 transition-opacity font-bold">{h.time}</div>
                                    <div className="flex justify-center mb-3">
                                      <WeatherIcon weather={h.weather} isNight={isHourNight} size={28} />
                                    </div>
                                    <div className="text-xs font-bold mb-2 truncate leading-tight h-4">{h.weather}</div>
                                    <div className="text-base font-serif font-bold text-emerald-300 mb-1">{h.pop}</div>
                                    <div className="text-xs opacity-90 font-mono">{h.temp}</div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                          
                          {weatherTranslation && (
                            <div className="bg-emerald-950/60 border-l-4 border-emerald-400 p-4 rounded-r-sm text-emerald-100 mt-6 shadow-inner">
                              <p className="text-sm font-bold tracking-wide leading-relaxed">
                                {weatherTranslation}
                              </p>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="text-xs opacity-70 italic">天気データは利用できません。</p>
                      )}
                    </div>

                  </div>

                  {/* 右カラム（位置情報、宇宙、海、歴史） */}
                  <div className="space-y-10">
                    <div className="bg-white/5 border border-white/10 p-6 md:p-8 rounded-sm h-fit">
                    <h3 className="text-xs font-bold uppercase tracking-widest text-emerald-300 mb-6 flex items-center gap-2">
                      <MapPin className="w-3 h-3" /> 選択地域の位置情報
                    </h3>
                    <div className="space-y-4">
                       <div className="flex justify-between items-center bg-white/5 p-4 rounded">
                         <span className="text-xs font-bold text-emerald-400">緯度・経度</span>
                         <span className="text-sm font-mono tracking-tighter">{coord.lat.toFixed(4)}, {coord.lng.toFixed(4)}</span>
                       </div>
                       {coord.elevation !== undefined && (
                         <div className="flex justify-between items-center bg-white/5 p-4 rounded">
                           <span className="text-xs font-bold text-emerald-400">おおよその標高 (AI推定)</span>
                           <span className="text-sm font-mono tracking-tighter">{coord.elevation} m</span>
                         </div>
                       )}
                       
                       <div className="w-full py-6 rounded-sm border border-white/10 mt-4 relative bg-stone-900/50 flex flex-col items-center justify-center">
                         <MapPin className="w-6 h-6 text-emerald-500/40 mb-2" />
                         <p className="text-emerald-100/70 text-xs md:text-sm mb-3 font-medium">詳細な位置確認はGoogle Mapsをご利用ください</p>
                         <a 
                           href={`https://www.google.com/maps/search/?api=1&query=${coord.lat},${coord.lng}`}
                           target="_blank"
                           rel="noopener noreferrer"
                           className="inline-flex items-center gap-2 px-5 py-2.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 rounded text-sm transition-colors border border-emerald-500/30 font-bold"
                         >
                           <MapPin className="w-4 h-4" /> Googleマップで開く
                         </a>
                       </div>
                    </div>
                  </div>

                  <div className="bg-white/5 border border-white/10 p-6 md:p-8 rounded-sm h-fit">
                    <h4 className="text-lg font-serif font-bold text-emerald-300 mb-2 flex items-center gap-3">
                      <Moon className="w-6 h-6" /> 今日の宇宙（そら）
                    </h4>
                    <p className="text-sm text-emerald-300 mb-6 font-serif">{locationName} - {selectedDate.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" })}</p>
                    <div className="grid grid-cols-2 gap-y-10 gap-x-12">
                      {[
                        { type: 'sunrise', data: sunriseData, label: '日の出時刻' },
                        { type: 'sunset', data: sunsetData, label: '日の入時刻' },
                        { type: 'moonrise', data: moonriseData, label: '月の出時刻' },
                        { type: 'moonset', data: moonsetData, label: '月の入時刻' }
                      ].map((evt, idx) => (
                          <div key={evt.type} onClick={() => setActiveAstro({ type: evt.type as any, time: evt.data.time, angle: evt.data.angle, isTomorrow: evt.data.isTomorrow })} className="cursor-pointer group">
                            <SimpleCompass angle={evt.data.angle} label={evt.label} />
                            <div className="text-center mt-4 flex items-center justify-center gap-2">
                              {evt.data.isTomorrow && <span className="text-[10px] font-sans font-bold text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded border border-amber-400/20 tracking-wider">翌日</span>}
                              <span className="text-2xl font-serif font-bold tracking-wider group-hover:text-amber-300 transition-colors">{evt.data.time ? evt.data.time.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" }) : "--:--"}</span>
                            </div>
                          </div>
                      ))}
                      
                      <div className="col-span-2 pt-6 border-t border-white/5">
                          <div className="flex justify-between items-center p-5 bg-white/5 rounded border border-white/5">
                            <div>
                              <span className="text-xs uppercase font-bold text-emerald-400 block mb-2 tracking-widest">現在の月齢</span>
                              <div className="flex items-baseline gap-2">
                                <span className="text-3xl font-serif font-bold tracking-widest text-white">{getLunarDetails(moonIllum.phase).lunarAge}</span>
                                <span className="text-emerald-100/60 font-medium text-sm">日</span>
                              </div>
                              <p className="text-sm text-emerald-300 mt-2 font-bold font-serif">{getLunarDetails(moonIllum.phase).moonName}</p>
                            </div>
                            <div className="flex flex-col items-center">
                              <MoonIllustration phase={moonIllum.phase} />
                            </div>
                          </div>
                      </div>
                    </div>
                  </div>

                        {/* Tide Data */}
                        <div className="pt-4 border-t border-white/10">
                          <h4 className="text-lg font-serif font-bold text-emerald-300 mb-2 flex items-center gap-3">
                            <Waves className="w-6 h-6" /> 今日の海 <span className="text-sm ml-2 font-medium bg-emerald-900/60 border border-emerald-500/30 text-emerald-200 px-2.5 py-0.5 rounded tracking-widest">{getLunarDetails(moonIllum.phase).tideName}</span>
                          </h4>
                          <p className="text-sm text-emerald-300 mb-6 font-serif">{locationName} - {selectedDate.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" })}</p>
                          {isLoading && (!tideData || (tideData.highTides.length === 0 && tideData.lowTides.length === 0)) ? (
                            <AILoadingState label="潮汐データ" />
                          ) : tideData && (tideData.highTides.length > 0 || tideData.lowTides.length > 0) ? (
                            <>
                            <div className="grid grid-cols-2 gap-x-12 gap-y-6">
                              <div className="space-y-4">
                                <div className="flex items-center gap-2 mb-2">
                                  <ChevronUp className="w-4 h-4 text-red-400" />
                                  <span className="text-xs text-red-300 font-bold uppercase tracking-widest">満潮 (High Tide)</span>
                                </div>
                                {tideData.highTides.map((t, idx) => {
                                  const displayLevel = typeof t.level === 'string' ? t.level : `${t.level}cm`;
                                  return (
                                  <div key={idx} className="flex justify-between items-baseline border-b border-white/10 pb-2">
                                    <span className="text-xl font-serif font-bold">{t.time}</span>
                                    <span className="text-base font-serif opacity-90">{displayLevel}</span>
                                  </div>
                                )})}
                              </div>
                              <div className="space-y-4">
                                <div className="flex items-center gap-2 mb-2">
                                  <ChevronDown className="w-4 h-4 text-blue-400" />
                                  <span className="text-xs text-blue-300 font-bold uppercase tracking-widest">干潮 (Low Tide)</span>
                                </div>
                                {tideData.lowTides.map((t, idx) => {
                                  const displayLevel = typeof t.level === 'string' ? t.level : `${t.level}cm`;
                                  return (
                                  <div key={idx} className="flex justify-between items-baseline border-b border-white/10 pb-2">
                                    <span className="text-xl font-serif font-bold">{t.time}</span>
                                    <span className="text-base font-serif opacity-90">{displayLevel}</span>
                                  </div>
                                )})}
                              </div>
                            </div>
                            
                            {tideStrategy && (
                              <div className="mt-6 bg-blue-950/60 border-l-4 border-blue-400 p-4 rounded-r-sm text-blue-100 shadow-inner">
                                <p className="text-sm font-bold tracking-wide leading-relaxed">
                                  {tideStrategy}
                                </p>
                              </div>
                            )}
                            </>
                          ) : tideData && tideData.oceanFallback ? (
                            <div className="bg-white/5 p-5 rounded border border-white/10 hover:border-emerald-500/30 transition-colors">
                              <a href={tideData.oceanFallback.url} target="_blank" rel="noopener noreferrer" className="block group">
                                <div className="flex justify-between items-start gap-4 mb-2">
                                  <span className="text-[10px] font-bold text-emerald-900 bg-emerald-400 px-1.5 py-0.5 rounded">
                                    {tideData.oceanFallback.location}
                                  </span>
                                  <span className="text-[10px] font-mono text-emerald-200/60">{tideData.oceanFallback.date}</span>
                                </div>
                                <p className="text-sm leading-relaxed text-emerald-50 group-hover:text-emerald-300 transition-colors font-medium">
                                  {tideData.oceanFallback.headline}
                                </p>
                                <div className="mt-2 flex items-center gap-1.5 text-[10px] text-emerald-400/80 group-hover:text-emerald-300 transition-colors font-bold uppercase tracking-tighter">
                                  <ExternalLink className="w-3 h-3" /> 最新情報を見る
                                </div>
                              </a>
                            </div>
                          ) : (
                            <div className="bg-white/5 p-6 rounded border border-white/5 text-center">
                              <p className="text-sm md:text-xs text-emerald-300/70 font-serif">
                                内陸地、または直近に潮汐情報の参照データがありません。<br/>
                                沿岸部へ移動するか、別の地点を検索してみてください。
                              </p>
                            </div>
                          )}

                          {marineData && (
                            <div className="mt-6 pt-6 border-t border-white/10 grid grid-cols-2 gap-x-12">
                              <div className="space-y-4">
                                <div className="flex items-center gap-2 mb-2">
                                  <span className="text-xs text-emerald-300 font-bold uppercase tracking-widest">波高 (Wave Height)</span>
                                </div>
                                <div className="flex justify-between items-baseline border-b border-white/10 pb-2">
                                  <span className="text-xl font-serif font-bold">{marineData.waveHeight}</span>
                                </div>
                              </div>
                              <div className="space-y-4">
                                <div className="flex items-center gap-2 mb-2">
                                  <span className="text-xs text-emerald-300 font-bold uppercase tracking-widest">周期 (Wave Period)</span>
                                </div>
                                <div className="flex justify-between items-baseline border-b border-white/10 pb-2">
                                  <span className="text-xl font-serif font-bold">{marineData.wavePeriod}</span>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>

                        {/* History section moved here */}
                        <div className="pt-8 mt-4 border-t border-white/10">
                          <h3 className="text-xl font-serif font-bold text-emerald-300 mb-2 flex items-center gap-3">
                            <Landmark className="w-6 h-6" /> 写真界の今日
                          </h3>
                          <p className="text-sm text-emerald-300 mb-8 font-serif">{selectedDate.toLocaleDateString("ja-JP", { month: "long", day: "numeric" })}に起きた歴史の記録</p>
                          <div className="space-y-8">
                            {isLoading && historyEvents.length === 0 ? (
                              <div className="py-2">
                                <AILoadingState label="写真史データ" />
                              </div>
                            ) : historyEvents.length > 0 ? historyEvents.map((ev, i) => (
                              <motion.div 
                                initial={{ opacity: 0, x: -10 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: i * 0.1 }}
                                key={i} 
                                className="group border-b border-white/5 pb-4 last:border-0 hover:border-emerald-500/30 transition-colors"
                              >
                                <p className="text-base md:text-sm italic text-emerald-50/95 leading-relaxed mb-3 font-medium">
                                  {ev.event}
                                </p>
                                {ev.url && (
                                  <a href={ev.url} target="_blank" rel="noopener noreferrer" className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors flex items-center gap-1.5 font-bold uppercase tracking-tighter">
                                    <ExternalLink className="w-3 h-3" /> 歴史的出典を確認する
                                  </a>
                                )}
                              </motion.div>
                            )) : (
                               <div className="bg-white/5 p-8 rounded border border-dashed border-white/10 text-center">
                                 <p className="text-sm text-emerald-300/70 font-serif">
                                   この日の写真史に関する記録をAIが整理中です。<br/>
                                   偉大な写真家たちの軌跡を検索しています。
                                 </p>
                               </div>
                            )}
                          </div>
                        </div>
                  </div>
                </div>
              </div>
            </section>



          </div>

          {/* Side Column */}
          <div className="space-y-10 md:space-y-12">
            
            {/* News Pickups */}
            <section className="bg-stone-100 p-8 md:p-8 rounded-sm shadow-sm transition-all duration-500 border border-stone-200">
              <h2 className="text-xl md:text-xl font-serif mb-8 flex items-center gap-3 text-emerald-950 font-bold">
                <Navigation className="w-6 h-6 text-emerald-800" /> 旬撮・最新ニュース 
                <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full font-bold ml-auto">RECENT</span>
              </h2>
              <div className="space-y-8">
                {isLoading && seasonalNews.length === 0 ? (
                   <AILoadingState label="撮影地ニュース" />
                ) : seasonalNews.length > 0 ? seasonalNews.map((news, i) => (
                  <motion.div 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.1 }}
                    key={i} 
                    className="group border-b border-stone-300 last:border-0 pb-6"
                  >
                    <a href={news.url} target="_blank" rel="noopener noreferrer" className="block hover:translate-x-2 transition-transform">
                      <div className="flex justify-between items-start gap-4 mb-3">
                        <span className="text-xs font-bold text-emerald-700 bg-emerald-100/50 px-2 py-1 rounded border border-emerald-200">
                          {news.location}
                        </span>
                        <span className="text-xs font-mono text-stone-500">{news.date}</span>
                      </div>
                      <p className="text-base leading-relaxed text-stone-900 group-hover:text-emerald-900 transition-colors font-bold">
                        {news.headline}
                      </p>
                      <div className="mt-3 flex items-center gap-2 text-xs text-stone-500 group-hover:text-emerald-700 transition-colors font-bold uppercase tracking-tighter">
                        <ExternalLink className="w-3.5 h-3.5" /> 詳細ニュースを読む
                      </div>
                    </a>
                  </motion.div>
                )) : (
                  <div className="text-center py-10 bg-white/50 rounded border border-dashed border-stone-400/30">
                    <p className="text-sm text-stone-600 font-serif leading-relaxed px-4">
                      現在、{locationName}周辺の最新撮影情報を検索中です。<br/>
                      事実ベースの一次情報を抽出しています。
                    </p>
                  </div>
                )}
              </div>
              <div className="mt-10 pt-8 border-t border-stone-200">
                <Link to="/archive" className="w-full flex flex-col items-center justify-center gap-2 py-6 bg-emerald-950 border border-emerald-900 text-white rounded-sm hover:bg-emerald-900 transition-all shadow-md group">
                  <div className="flex items-center gap-3 text-lg md:text-xl font-bold font-serif tracking-widest">
                    <Calendar className="w-5 h-5 text-emerald-300 group-hover:scale-110 transition-transform" /> 旬撮情報アーカイブ
                  </div>
                  <span className="text-xs md:text-sm text-emerald-100/70 font-medium tracking-widest font-sans">（＋カテゴリー別絞り込み）</span>
                </Link>
              </div>
            </section>

            {/* Gallery Info */}
            <section className="bg-white p-8 md:p-8 rounded-sm border border-stone-200 shadow-sm relative overflow-hidden">
              <div className="absolute -right-4 -bottom-4 opacity-5 pointer-events-none">
                <Landmark className="w-32 h-32" />
              </div>
              <h2 className="text-xl md:text-xl font-serif mb-4 flex items-center gap-3 relative z-10 text-emerald-950 font-bold">
                <Camera className="w-6 h-6 text-emerald-800" /> 写真展情報
              </h2>
              
              <div className="flex flex-wrap gap-2 mb-8 relative z-10">
                {Object.keys(galleriesByRegion).map(region => (
                  <button 
                    key={region} 
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById(`gallery-region-${region}`)?.scrollIntoView({ behavior: 'smooth' });
                    }}
                    className="text-sm font-bold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full hover:bg-emerald-100 hover:text-emerald-900 transition-colors"
                  >
                    {region}
                  </button>
                ))}
              </div>

              <div className="space-y-12 relative z-10">
                {Object.entries(galleriesByRegion).map(([region, regionGalleries]) => (
                  <div key={region} id={`gallery-region-${region}`} className="scroll-mt-24">
                    <h3 className="text-lg font-bold text-stone-800 mb-4 border-b-2 border-stone-100 pb-2 flex items-center gap-2">
                       <MapPin className="w-5 h-5 text-stone-400" /> {region}
                    </h3>
                    <ul className="space-y-6">
                      {regionGalleries.map((gallery, i) => (
                          <li key={i} className="group pb-2">
                              <div className="block">
                                  <a href={gallery.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 hover:translate-x-1 transition-transform">
                                      <h4 className="text-base font-bold text-emerald-900">
                                          {gallery.name}
                                      </h4>
                                      <ExternalLink className="w-3.5 h-3.5 text-emerald-900 opacity-0 group-hover:opacity-100 transition-opacity" />
                                  </a>
                                  <div className="flex items-center gap-1.5 text-sm font-medium mt-1">
                                      <MapPin className="w-3.5 h-3.5 text-stone-400" />
                                      <a 
                                        href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(gallery.name + ' ' + gallery.access)}`} 
                                        target="_blank" 
                                        rel="noopener noreferrer" 
                                        className="text-stone-500 hover:text-emerald-600 transition-colors"
                                        title="Googleマップで開く"
                                      >
                                        {gallery.access}
                                      </a>
                                  </div>
                              </div>
                          </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </section>

            {/* Paper Sizes */}
            <section className="bg-emerald-950 text-white p-8 md:p-8 rounded-sm shadow-xl">
              <h2 className="text-2xl md:text-2xl font-serif mb-8 flex items-center gap-3 text-emerald-400 font-bold">
                <ArrowLeftRight className="w-6 h-6" /> 写真用紙サイズ
              </h2>
              <div className="space-y-4">
                {paperSizes.map((item, i) => (
                  <div key={i} className="flex justify-between items-center py-3 border-b border-white/10 last:border-0">
                    <span className="text-lg font-bold text-emerald-200">{item.size}</span>
                    <span className="font-mono text-sm opacity-70">{item.dimensions}</span>
                  </div>
                ))}
              </div>
            </section>

          </div>
        </div>
        {/* Guide Modal */}
        <AnimatePresence>
          {isGuideOpen && (
            <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
              <motion.div 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={() => setIsGuideOpen(false)}
                className="absolute inset-0 bg-emerald-950/80 backdrop-blur-sm"
              />
              <motion.div 
                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 20 }}
                className="relative bg-white text-stone-900 w-full max-w-2xl rounded-sm shadow-2xl overflow-hidden"
              >
                <div className="flex justify-between items-center p-6 border-b border-stone-100 bg-emerald-900 text-white">
                  <h3 className="font-serif text-xl flex items-center gap-2">
                    <HelpCircle className="w-5 h-5 text-emerald-400" /> 【今日も風景写真日和】の使い方
                  </h3>
                  <button 
                    onClick={() => setIsGuideOpen(false)}
                    className="p-2 hover:bg-white/10 rounded-full transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
                <div className="p-8 max-h-[70vh] overflow-y-auto space-y-8">
                  <section>
                    <h4 className="font-bold text-emerald-800 mb-3 flex items-center gap-2">
                      <span className="flex items-center justify-center w-5 h-5 bg-emerald-100 text-emerald-800 rounded-full text-xs italic">1</span>
                      入力による情報の変化
                    </h4>
                    <div className="space-y-4 text-sm leading-relaxed text-stone-600 pl-7">
                      <p>操作パネルで「地名」や「日付」を変更すると、風景写真家に必要な様々なデータがAIによって即座に再構成されます。</p>
                      <ul className="list-disc pl-5 space-y-2">
                        <li><strong className="text-stone-900">地名変更の影響:</strong> 日の出・日の入・月の出・月の入時刻、潮位データ、周辺の写真ニュースがその場所に合わせて更新されます。</li>
                        <li><strong className="text-stone-900">日付変更の影響:</strong> 二十四節気・七十二候、写真史の出来事、月齢、および上記すべての項目が指定した日付の内容に切り替わります。</li>
                        <li><strong className="text-stone-900">変化しないもの:</strong> 推奨プリントサイズ一覧や、主要な写真展情報などの汎用的なリファレンスデータは固定されています。</li>
                      </ul>
                    </div>
                  </section>

                  <section>
                    <h4 className="font-bold text-emerald-800 mb-3 flex items-center gap-2">
                      <span className="flex items-center justify-center w-5 h-5 bg-emerald-100 text-emerald-800 rounded-full text-xs italic">2</span>
                      地名の入力詳細度
                    </h4>
                    <div className="space-y-3 text-sm leading-relaxed text-stone-600 pl-7">
                      <p>都道府県、市区町村レベルはもちろん、特定のスポット名（例：「千鳥ヶ淵」「富士山五合目」など）にも対応しています。</p>
                      <p className="bg-emerald-50 p-4 rounded-sm border-l-2 border-emerald-500 italic">
                        入力された地名が主要都市リストにない場合でも、AIが即座にその場所の最新の緯度・経度を特定し、その正確な座標に基づいて天体時刻を再計算します。
                      </p>
                    </div>
                  </section>

                  <section>
                    <h4 className="font-bold text-emerald-800 mb-3 flex items-center gap-2">
                      <span className="flex items-center justify-center w-5 h-5 bg-emerald-100 text-emerald-800 rounded-full text-xs italic">3</span>
                      情報の精度と制限
                    </h4>
                    <div className="space-y-3 text-sm leading-relaxed text-stone-600 pl-7">
                      <ul className="list-disc pl-5 space-y-2">
                        <li><strong className="text-stone-900">天気予報:</strong> 本日を基準に前後数日間（AIが外部ソースから確度の高い情報を取得できる範囲）のみ表示されます。</li>
                        <li><strong className="text-stone-900">制限事項:</strong> 数ヶ月先の未来や数年以上前の過去を指定した場合、天気や降水確率は「データなし」と表示されることがあります。</li>
                        <li><strong className="text-stone-900">潮汐データ:</strong> 天体計算に基づくAIの推定値です。航海等の安全確認には使用しないでください。</li>
                      </ul>
                    </div>
                  </section>
                </div>
                <div className="p-6 bg-stone-50 border-t border-stone-100 flex justify-end">
                  <button 
                    onClick={() => setIsGuideOpen(false)}
                    className="px-6 py-2 bg-emerald-800 text-white rounded-sm font-bold hover:bg-emerald-700 transition-colors"
                  >
                    閉じる
                  </button>
                </div>
              </motion.div>
            </div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default ReferencePage;
