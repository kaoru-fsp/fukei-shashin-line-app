import { useState, useEffect } from "react";
import { motion } from "motion/react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, Sparkles, Loader2, MapPin, Calendar } from "lucide-react";
import { fetchAISummary } from "../services/geminiReferenceService";

export default function AISummaryPage() {
  const [summary, setSummary] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const location = useLocation();
  const navigate = useNavigate();

  const state = location.state as {
    locationName: string;
    selectedDate: string; // ISO string
    dataToSummarize: string;
  } | null;

  useEffect(() => {
    // If accessed directly without state, redirect back to reference
    if (!state || !state.locationName) {
      navigate('/reference');
      return;
    }

    const loadSummary = async () => {
      setLoading(true);
      try {
        const dateObj = new Date(state.selectedDate);
        const result = await fetchAISummary(state.locationName, dateObj, state.dataToSummarize);
        setSummary(result);
      } catch (err) {
        console.error(err);
        setSummary("サマリーの取得中にエラーが発生しました。");
      } finally {
        setLoading(false);
      }
    };

    loadSummary();
  }, [state, navigate]);

  if (!state) return null;

  const dateObj = new Date(state.selectedDate);
  const formattedDate = dateObj.toLocaleDateString("ja-JP", { year: "numeric", month: "long", day: "numeric" });

  return (
    <div className="min-h-screen bg-emerald-950 text-emerald-50 py-12 px-6">
      <div className="max-w-3xl mx-auto pt-16">
        <Link to="/reference" className="inline-flex items-center gap-2 text-emerald-400 hover:text-emerald-300 transition-colors mb-8 text-sm font-bold tracking-wider uppercase">
          <ArrowLeft className="w-4 h-4" /> 撮影計画へ戻る
        </Link>
        
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-emerald-900 border border-emerald-700/50 rounded-lg p-8 md:p-12 shadow-2xl relative overflow-hidden"
        >
          {/* Decorative Background */}
          <div className="absolute -top-32 -right-32 w-64 h-64 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-32 -left-32 w-64 h-64 bg-amber-500/10 rounded-full blur-3xl pointer-events-none" />

          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-6">
              <Sparkles className="w-8 h-8 text-amber-400" />
              <h1 className="text-3xl md:text-4xl font-serif text-white tracking-tight">AI 撮影サマリー</h1>
            </div>

            <div className="flex flex-wrap items-center gap-4 text-emerald-300 mb-10 pb-6 border-b border-emerald-800/50 font-medium">
              <div className="flex items-center gap-2 bg-emerald-950/50 px-3 py-1.5 rounded-full border border-emerald-800/50">
                <MapPin className="w-4 h-4 text-emerald-500" />
                <span>{state.locationName}</span>
              </div>
              <div className="flex items-center gap-2 bg-emerald-950/50 px-3 py-1.5 rounded-full border border-emerald-800/50">
                <Calendar className="w-4 h-4 text-emerald-500" />
                <span>{formattedDate}</span>
              </div>
            </div>

            <div className="min-h-[200px]">
              {loading ? (
                <div className="flex flex-col items-center justify-center h-48 text-emerald-400/80 gap-4">
                  <Loader2 className="w-8 h-8 animate-spin" />
                  <p className="font-serif animate-pulse text-lg">AIが撮影プランを分析・要約しています...</p>
                </div>
              ) : (
                <motion.div 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.5 }}
                  className="prose prose-invert prose-emerald max-w-none font-serif leading-loose text-lg text-emerald-100/90 whitespace-pre-wrap"
                >
                  {summary}
                </motion.div>
              )}
            </div>
            
            {!loading && (
              <div className="mt-12 pt-6 border-t border-emerald-800/50 flex justify-end">
                 <Link to="/reference" className="px-6 py-3 bg-emerald-800/30 border border-emerald-700/50 text-emerald-300 rounded hover:bg-emerald-800/50 transition-colors font-bold flex items-center gap-2">
                   <ArrowLeft className="w-4 h-4" /> 確認完了
                 </Link>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
