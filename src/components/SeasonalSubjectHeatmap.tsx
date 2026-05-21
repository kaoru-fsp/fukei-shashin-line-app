import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Map as MapIcon, 
  Mountain, 
  Snowflake, 
  Sun, 
  CloudRain, 
  TreePine, 
  Flower2, 
  Waves, 
  Star, 
  Leaf,
  Maximize2
} from 'lucide-react';
import { collection, query, where, limit, getDocs } from 'firebase/firestore';
import { db } from '../firebase';
import FullScreenGallery from './FullScreenGallery';

interface ContestPhoto {
  id?: string;
  Month?: string;
  Area?: string;
  Subject?: string;
  [key: string]: any;
}

interface HeatmapProps {
  currentMonth: number;
}

const PREFECTURES = [
  "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
  "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
  "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
  "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
  "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
  "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
  "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"
];

function getSubjectIcon(name: string) {
  if (name.includes('桜') || name.includes('花')) return <Flower2 className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  if (name.includes('雪') || name.includes('氷')) return <Snowflake className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  if (name.includes('山') || name.includes('岳')) return <Mountain className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  if (name.includes('朝') || name.includes('夕') || name.includes('陽')) return <Sun className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  if (name.includes('海') || name.includes('波') || name.includes('湖')) return <Waves className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  if (name.includes('木') || name.includes('森') || name.includes('林')) return <TreePine className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  if (name.includes('霧') || name.includes('雲')) return <CloudRain className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  if (name.includes('星')) return <Star className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
  return <Leaf className="w-5 h-5 opacity-70 group-hover:opacity-100 transition-opacity" />;
}

export default function SeasonalSubjectHeatmap({ currentMonth }: HeatmapProps) {
  const [allPhotos, setAllPhotos] = useState<ContestPhoto[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fullScreenPhotos, setFullScreenPhotos] = useState<ContestPhoto[] | null>(null);

  const handleSubjectClick = (subjectName: string) => {
    // Collect all photos containing this subject
    const relatedPhotos = allPhotos.filter(p => p.Subject?.includes(subjectName));
    if (relatedPhotos.length > 0) {
      setFullScreenPhotos(relatedPhotos);
    }
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        setIsLoading(true);
        const monthStr = currentMonth.toString();
        const monthZero = monthStr.padStart(2, "0");
        const monthNum = currentMonth;
        const monthVariants = [monthStr, monthZero, monthNum];

        // 究極のフォールバック (全くの無条件200件)
        let docs: any[] = [];
        try {
          const snap = await getDocs(query(collection(db, "contests"), limit(200)));
          docs = snap.docs;
          console.log("🔥 Loaded generic heatmap docs count:", docs.length);
        } catch (e) {
          console.error("🔥 Error loading generic heatmap docs:", e);
        }

        const data: ContestPhoto[] = [];
        docs.forEach((doc) => {
          data.push({ id: doc.id, ...doc.data() } as ContestPhoto);
        });
        setAllPhotos(data);
      } catch (err) {
        console.error("Failed to load contest data from Firestore:", err);
      } finally {
        setIsLoading(false);
      }
    };
    fetchData();
  }, [currentMonth]);

  const stats = useMemo(() => {
    if (!allPhotos.length) return null;

    // Utilize all data unconditionally
    let thisMonthPhotos = allPhotos;

    const subjectsCount: Record<string, number> = {};
    const prefectureCount: Record<string, number> = {};
    const prefectureSubjects: Record<string, Record<string, number>> = {};

    thisMonthPhotos.forEach(p => {
      if (p.Subject) {
        const subjects = p.Subject.split(/　| /).map(s => s.trim()).filter(Boolean);
        subjects.forEach(subject => {
          if (subject.length > 0) {
              subjectsCount[subject] = (subjectsCount[subject] || 0) + 1;
          }
        });
      }

      if (p.Area) {
        const prefMatch = PREFECTURES.find(pref => p.Area?.includes(pref));
        if (prefMatch) {
          prefectureCount[prefMatch] = (prefectureCount[prefMatch] || 0) + 1;
          if (!prefectureSubjects[prefMatch]) prefectureSubjects[prefMatch] = {};
          
          if (p.Subject) {
            const subjects = p.Subject.split(/　| /).map(s => s.trim()).filter(Boolean);
            subjects.forEach(subject => {
               if (subject.length > 0) {
                 prefectureSubjects[prefMatch][subject] = (prefectureSubjects[prefMatch][subject] || 0) + 1;
               }
            });
          }
        }
      }
    });

    const topSubjects = Object.entries(subjectsCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([name, count]) => ({ name, count }));

    const topRegions = Object.entries(prefectureCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([name, count]) => {
          let topSubj = "";
          if (prefectureSubjects[name]) {
              const sortedSubj = Object.entries(prefectureSubjects[name]).sort((a, b) => b[1] - a[1]);
              if (sortedSubj.length > 0) topSubj = sortedSubj[0][0];
          }
          return { name, count, topSubject: topSubj };
      });

    return { topSubjects, topRegions, totalCount: thisMonthPhotos.length };
  }, [allPhotos, currentMonth]);

  if (isLoading) return null;
  if (!stats || stats.totalCount === 0) return null;

  return (
    <div className="w-full mt-12 mb-12 bg-white/5 border border-emerald-900/40 rounded-xl p-6 md:p-8 backdrop-blur-sm">
      <div className="flex items-center gap-3 mb-8 border-b border-emerald-800/30 pb-4">
        <div className="p-2.5 bg-emerald-900/50 rounded-lg">
          <MapIcon className="w-6 h-6 text-emerald-400" />
        </div>
        <div>
          <h3 className="text-xl font-serif text-white tracking-wide">「旬の被写体」ヒートマップ</h3>
          <p className="text-sm text-emerald-400/80 mt-1 uppercase tracking-wider">全データ傾向分析 (Firestore連携)</p>
        </div>
        <div className="ml-auto text-right hidden sm:block">
          <div className="text-2xl font-bold text-emerald-300 font-mono">{stats.totalCount}</div>
          <div className="text-[10px] text-emerald-500/70 tracking-widest">DATA POINTS</div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-8 md:gap-12">
        {/* Hot Regions */}
        <div>
          <h4 className="text-sm font-bold text-emerald-400/60 uppercase tracking-widest mb-4 flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            撮影地トレンド
          </h4>
          <div className="space-y-4">
            {stats.topRegions.map((region, i) => (
              <div key={region.name} className="relative group">
                <div className="flex justify-between items-end mb-1 relative z-10">
                  <span className="text-white font-serif tracking-wide">{region.name}</span>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[10px] text-emerald-400/80 uppercase tracking-wider">{region.topSubject || "風景"}</span>
                    <span className="text-emerald-50 font-mono font-bold">{region.count}</span>
                  </div>
                </div>
                <div className="h-1.5 w-full bg-white/5 rounded-full overflow-hidden">
                  <motion.div 
                    initial={{ width: 0 }}
                    whileInView={{ width: `${Math.max(10, (region.count / stats.topRegions[0].count) * 100)}%` }}
                    viewport={{ once: true }}
                    transition={{ duration: 1, ease: "easeOut", delay: i * 0.1 }}
                    className="h-full bg-gradient-to-r from-emerald-600 to-emerald-400 rounded-full"
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Top Subjects */}
        <div>
          <h4 className="text-sm font-bold text-emerald-400/60 uppercase tracking-widest mb-4 flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-yellow-500" />
            人気の被写体
          </h4>
          <div className="grid grid-cols-2 gap-3">
            {stats.topSubjects.map((subj, i) => (
              <motion.div 
                key={subj.name}
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
                className="bg-emerald-950/30 border border-emerald-900/30 rounded-lg p-3 group hover:bg-emerald-900/40 transition-colors flex items-center justify-between cursor-pointer relative overflow-hidden"
                onClick={() => handleSubjectClick(subj.name)}
              >
                <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/0 via-emerald-500/0 to-emerald-500/10 opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                <div className="relative z-10">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-emerald-400 group-hover:text-emerald-300">
                      {getSubjectIcon(subj.name)}
                    </span>
                    <div className="text-emerald-50 font-serif whitespace-nowrap overflow-hidden text-ellipsis max-w-[120px] group-hover:text-white transition-colors">{subj.name}</div>
                  </div>
                  <div className="text-[10px] text-emerald-400/60 uppercase tracking-widest pl-7 flex items-center gap-1.5">
                    {subj.count} spots <Maximize2 className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                </div>
                <div className="text-2xl font-bold text-emerald-400/10 group-hover:text-emerald-400/20 font-mono leading-none transition-colors relative z-10">
                  0{i + 1}
                </div>
              </motion.div>
            ))}
          </div>
          
          {stats.topSubjects.length === 0 && (
            <div className="text-sm text-stone-500 italic py-4">データが不足しています</div>
          )}
        </div>
      </div>
      
      {fullScreenPhotos && (
        <FullScreenGallery
          photos={fullScreenPhotos}
          onClose={() => setFullScreenPhotos(null)}
        />
      )}
    </div>
  );
}
