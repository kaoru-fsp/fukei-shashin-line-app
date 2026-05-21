import React, { useState, useEffect, useMemo } from 'react';
import Papa from 'papaparse';
import { Search, ChevronLeft, ChevronRight, X, AlertCircle, Loader2 } from 'lucide-react';
import { motion } from 'motion/react';

import { 
  collection, 
  getDocs, 
  query, 
  orderBy, 
  limit, 
  startAfter, 
  startAt,
  getCountFromServer,
  DocumentData,
  QueryDocumentSnapshot
} from 'firebase/firestore';
import { db } from './firebase';

interface ContestRow {
  dNumb?: string;
  Published?: string;
  Department?: string;
  Theme?: string;
  Title?: string;
  Winner?: string;
  WinnerInfo?: string;
  Winner4Search?: string;
  Prefecture?: string;
  WinnerArea?: string;
  Area?: string;
  Place?: string;
  Camera?: string;
  Lens?: string;
  Film?: string;
  JudgeInfo?: string;
  PicFileName?: string;
  Month?: string;
  Season?: string;
  Year?: string;
  Subject?: string;
  id?: string;
  imageUrl?: string;
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

const ContestDatabasePage: React.FC = () => {
  const [data, setData] = useState<ContestRow[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searching, setSearching] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTermInput, setSearchTermInput] = useState<string>('');
  const [searchTerm, setSearchTerm] = useState<string>('');
  
  // Advanced search states
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [selectedRegions, setSelectedRegions] = useState<string[]>([]);
  const [selectedMonth, setSelectedMonth] = useState<string>('');
  const [activeRegions, setActiveRegions] = useState<string[]>([]);
  const [activeMonth, setActiveMonth] = useState<string>('');
  
  // Modal state
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  
  // Pagination state
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [lastDoc, setLastDoc] = useState<QueryDocumentSnapshot<DocumentData> | null>(null);
  const [pageHistory, setPageHistory] = useState<(QueryDocumentSnapshot<DocumentData> | null)[]>([null]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const itemsPerPage = 12;

  // 全件数を取得（初回のみ）
  useEffect(() => {
    const fetchCount = async () => {
      try {
        const coll = collection(db, "contests");
        const snapshot = await getCountFromServer(coll);
        setTotalCount(snapshot.data().count);
      } catch (err) {
        console.error("Failed to fetch count:", err);
      }
    };
    fetchCount();
  }, []);

  const loadData = async (page: number, direction: 'next' | 'prev' | 'first' = 'next') => {
    try {
      setLoading(true);
      const contestsRef = collection(db, "contests");
      let q;

      // 基本クエリ（dNumbでソート。文字列としてのソートになる点に注意）
      const baseConstraints = [orderBy("dNumb", "asc"), limit(itemsPerPage)];

      if (searchTerm || activeRegions.length > 0 || activeMonth) {
        setSearching(true);
        // 検索時はFirestoreの制限により、ここでは一旦多めに取得してクライアントでフィルタリングする
        // 1.5万件を一度には呼び出さない（iPhone対策）
        q = query(contestsRef, ...baseConstraints, limit(500)); 
      } else {
        setSearching(false);
        if (direction === 'next' && lastDoc && page > 1) {
          q = query(contestsRef, ...baseConstraints, startAfter(lastDoc));
        } else if (direction === 'prev' && pageHistory[page - 1] !== undefined) {
          const prevStartDoc = pageHistory[page - 1];
          q = prevStartDoc 
            ? query(contestsRef, ...baseConstraints, startAt(prevStartDoc))
            : query(contestsRef, ...baseConstraints);
        } else {
          q = query(contestsRef, ...baseConstraints);
        }
      }

      const querySnapshot = await getDocs(q);
      const fetchedData: ContestRow[] = [];
      
      querySnapshot.forEach((doc) => {
        const d = doc.data() as ContestRow;
        fetchedData.push({ 
          ...d,
          id: doc.id, 
          Winner4Search: d.Winner4Search || "",
          Prefecture: d.WinnerArea || d.Prefecture || d.Area,
          Theme: d.Theme || d.Subject
        } as ContestRow);
      });

      if (querySnapshot.docs.length > 0) {
        setLastDoc(querySnapshot.docs[querySnapshot.docs.length - 1]);
        if (direction === 'next' && page > pageHistory.length) {
          setPageHistory(prev => [...prev, querySnapshot.docs[0]]);
        }
      }

      setData(fetchedData);
      setError(null);
    } catch (err: any) {
      console.error("Firestore loading error:", err);
      setError('データの読み取りに失敗しました。');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(1, 'first');
  }, [searchTerm, activeRegions, activeMonth]);

  const filteredData = useMemo(() => {
    if (!searching) return data;

    return data.filter((row) => {
      let matchesKeyword = true;
      if (searchTerm.trim()) {
        const lowerSearchTerm = searchTerm.toLowerCase();
        matchesKeyword = !!(
          (row.Title && row.Title.toLowerCase().includes(lowerSearchTerm)) ||
          (row.Winner4Search && row.Winner4Search.toLowerCase().includes(lowerSearchTerm)) ||
          (row.Department && row.Department.toLowerCase().includes(lowerSearchTerm)) ||
          (row.Theme && row.Theme.toLowerCase().includes(lowerSearchTerm)) ||
          (row.Prefecture && row.Prefecture.toLowerCase().includes(lowerSearchTerm)) ||
          (row.Camera && row.Camera.toLowerCase().includes(lowerSearchTerm))
        );
      }

      let matchesRegion = true;
      if (activeRegions.length > 0) {
        matchesRegion = activeRegions.some(region => 
          (row.Prefecture && row.Prefecture.includes(region)) || 
          (row.Area && row.Area.includes(region))
        );
      }

      let matchesMonth = true;
      if (activeMonth) {
        const m = activeMonth.replace('月', '');
        matchesMonth = 
          (row.Month === m) || 
          (row.Season === activeMonth) || 
          (row.Published && row.Published.includes(activeMonth)) ||
          (row.Season && row.Season.includes(activeMonth)) || false;
      }

      return matchesKeyword && matchesRegion && matchesMonth;
    });
  }, [data, searchTerm, activeRegions, activeMonth, searching]);

  const currentData = searching ? filteredData.slice(0, itemsPerPage) : filteredData;
  const totalPages = searching ? Math.ceil(filteredData.length / itemsPerPage) : Math.ceil(totalCount / itemsPerPage);

  const handlePageChange = (page: number) => {
    if (page > currentPage) {
      loadData(page, 'next');
    } else {
      loadData(page, 'prev');
    }
    setCurrentPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // 検索入力時に1ページ目に戻す
  useEffect(() => {
    setCurrentPage(1);
  }, [searchTerm]);

  return (
    <div className="pt-24 pb-16 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="mb-8 relative">
           <img 
              src="https://images.unsplash.com/photo-1469474968028-56623f02e42e?q=80&w=2000&auto=format&fit=crop" 
              alt="Contest Library Header" 
              className="w-full h-48 md:h-64 object-cover rounded-xl brightness-75"
              referrerPolicy="no-referrer"
           />
           <div className="absolute inset-0 flex flex-col items-center justify-center text-white">
              <h1 className="text-3xl md:text-5xl font-serif font-bold mb-4 tracking-wider">Contest Library</h1>
              <p className="text-sm md:text-base font-medium opacity-90 max-w-2xl px-4 text-center">
                 『風景写真』フォトコンテスト受賞作品ライブラリ
              </p>
              <a href="/import" className="mt-4 text-xs bg-white text-gray-900 px-3 py-1.5 rounded-full font-bold shadow-md hover:bg-gray-100 transition">
                 【開発用】CSV一括インポートツールへ
              </a>
           </div>
        </div>

        <div className="bg-white p-6 rounded-xl shadow-sm mb-8">
          <form 
            className="flex flex-col max-w-4xl mx-auto gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              setSearchTerm(searchTermInput);
              setActiveRegions(selectedRegions);
              setActiveMonth(selectedMonth);
            }}
          >
            <div className="flex gap-2">
              <div className="relative flex-1">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Search className="h-5 w-5 text-gray-400" />
                </div>
                <input
                  type="text"
                  placeholder="作品名、受賞者、部門などで検索..."
                  value={searchTermInput}
                  onChange={(e) => setSearchTermInput(e.target.value)}
                  className="block w-full pl-10 pr-10 py-3 border border-gray-200 rounded-lg leading-5 bg-gray-50 placeholder-gray-400 focus:outline-none focus:bg-white focus:ring-2 focus:ring-gray-900 focus:border-transparent transition-all"
                />
                {(searchTermInput || selectedRegions.length > 0 || selectedMonth) && (
                  <button
                    type="button"
                    onClick={() => {
                      setSearchTermInput('');
                      setSearchTerm('');
                      setSelectedRegions([]);
                      setActiveRegions([]);
                      setSelectedMonth('');
                      setActiveMonth('');
                    }}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center"
                    title="クリア"
                  >
                    <X className="h-4 w-4 text-gray-400 hover:text-gray-600" />
                  </button>
                )}
              </div>
              <button 
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className={`px-4 rounded-lg font-medium transition duration-200 border ${showAdvanced ? 'bg-gray-100 border-gray-300 text-gray-800' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}`}
              >
                詳細検索
              </button>
              <button 
                type="submit"
                className="bg-gray-900 hover:bg-gray-800 text-white px-6 rounded-lg font-medium transition duration-200"
              >
                検索
              </button>
            </div>

            {showAdvanced && (
              <motion.div 
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="bg-gray-50 border border-gray-200 rounded-lg p-4 grid grid-cols-1 md:grid-cols-2 gap-6"
              >
                <div>
                  <h4 className="text-sm font-bold text-gray-700 mb-2">地域 (複数選択可 / OR検索)</h4>
                  <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto p-2 bg-white border border-gray-200 rounded-md">
                    {PREFECTURES.map(pref => (
                      <button
                        key={pref}
                        type="button"
                        onClick={() => {
                          if (selectedRegions.includes(pref)) {
                            setSelectedRegions(selectedRegions.filter(r => r !== pref));
                          } else {
                            setSelectedRegions([...selectedRegions, pref]);
                          }
                        }}
                        className={`text-xs px-2 py-1 rounded-full border transition-colors ${selectedRegions.includes(pref) ? 'bg-blue-100 border-blue-300 text-blue-800' : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'}`}
                      >
                        {pref}
                      </button>
                    ))}
                  </div>
                </div>
                
                <div>
                  <h4 className="text-sm font-bold text-gray-700 mb-2">時期</h4>
                  <div className="flex flex-wrap gap-2">
                    {["春", "夏", "秋", "冬", ...Array.from({length: 12}, (_, i) => String(i + 1) + "月")].map(m => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setSelectedMonth(selectedMonth === m ? '' : m)}
                        className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${selectedMonth === m ? 'bg-orange-100 border-orange-300 text-orange-800' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}
          </form>
          <p className="text-center text-sm text-gray-500 mt-3">
             {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  読み込み中...
                </span>
             ) : (
                `該当件数: ${searching ? filteredData.length + (filteredData.length >= 500 ? "+" : "") : totalCount.toLocaleString()}件`
             )}
          </p>
        </div>

        {error && (
          <div className="bg-red-50 text-red-600 p-4 rounded-lg flex items-start gap-3 mb-8 shadow-sm border border-red-100">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <p className="text-sm font-medium">{error}</p>
          </div>
        )}

        {loading && data.length === 0 ? (
          <div className="flex flex-col justify-center items-center h-64 gap-4 bg-white rounded-xl shadow-sm border border-gray-100">
             <div className="relative">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900"></div>
                <div className="absolute inset-0 flex items-center justify-center">
                   <div className="w-2 h-2 bg-gray-900 rounded-full"></div>
                </div>
             </div>
             <div className="text-center">
                <p className="text-gray-900 font-bold">先遣隊、突入中！</p>
                <p className="text-gray-400 text-xs mt-1">膨大なデータベースをスキャンしています</p>
             </div>
          </div>
        ) : filteredData.length === 0 && !loading ? (
          <div className="text-center py-20 bg-white rounded-xl shadow-sm">
            <p className="text-gray-600 text-lg">検索条件に一致する作品が見つかりませんでした。</p>
            <button 
              onClick={() => {
                setSearchTermInput('');
                setSearchTerm('');
                setSelectedRegions([]);
                setActiveRegions([]);
                setSelectedMonth('');
                setActiveMonth('');
              }}
              className="mt-4 text-blue-600 hover:underline font-medium"
            >
              検索条件をクリアする
            </button>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
              {currentData.map((row, index) => {
                const generateImageUrl = (published?: string, picFileName?: string) => {
                  if (!published || !picFileName) return '';
                  const cleanPub = published.trim();
                  const cleanFileName = picFileName.trim();
                  const year = cleanPub.substring(0, 4);
                  // Ensure no double slashes in the constructed path
                  const rawPath = `/PicsDB/PicsDB4Search/${year}/${cleanPub}/${cleanFileName}`;
                  const cleanPath = rawPath.replace(/\/\/+/g, '/');
                  const url = `https://fupc.photo${cleanPath}`;
                  return url;
                };
                const imageUrl = generateImageUrl(row.Published, row.PicFileName);
                if (index === 0) {
                  // 出力確認用
                  console.log(`[Database] Example URL mapping for index 0 - Title: ${row.Title}, Winner: ${row.Winner4Search}, URL: ${imageUrl}`);
                }
                return (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.05 }}
                    key={row.dNumb || index}
                    className="bg-white rounded-xl overflow-hidden shadow-sm border border-gray-100 group cursor-pointer"
                    onClick={() => imageUrl && setSelectedImage(imageUrl)}
                  >
                    <div className="aspect-[4/3] bg-gray-50 overflow-hidden relative border-b border-gray-100">
                      {imageUrl ? (
                        <img 
                          src={imageUrl} 
                          alt={row.Title || "Untitled"} 
                          className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                          loading="lazy"
                          onError={(e) => {
                            console.error("Image failed to load:", imageUrl);
                            const target = e.target as HTMLImageElement;
                            // 画像エラー時は枠だけ表示（非表示にする）
                            target.style.display = 'none';
                            const parent = target.parentElement;
                            if (parent) {
                              const noImage = document.createElement('div');
                              noImage.className = 'w-full h-full flex flex-col items-center justify-center text-gray-300 bg-gray-50';
                              noImage.innerHTML = '<span class="text-xs font-bold tracking-widest">NO IMAGE</span>';
                              parent.appendChild(noImage);
                            }
                          }}
                        />
                      ) : (
                         <div className="w-full h-full flex items-center justify-center text-gray-300 bg-gray-50">
                           <span className="text-xs font-bold tracking-widest">NO IMAGE</span>
                         </div>
                      )}
                      
                      <div className="absolute top-2 left-2 flex flex-col gap-1">
                        {row.Published && (
                          <span className="bg-black/70 backdrop-blur-md text-white text-[10px] px-2 py-1 rounded-sm font-medium tracking-wide">
                            {row.Published}
                          </span>
                        )}
                        {row.Department && (
                          <span className="bg-white/90 backdrop-blur-md text-gray-900 text-[10px] px-2 py-1 rounded-sm font-medium tracking-wide border border-gray-200">
                            {row.Department}
                          </span>
                        )}
                      </div>
                    </div>
                    
                    <div className="p-4">
                      <h3 className="font-serif font-bold text-lg text-gray-900 mb-1 line-clamp-1">{row.Title || "無題"}</h3>
                      <p className="text-sm font-medium text-gray-700 mb-3 line-clamp-1">{row.Winner4Search || ""}</p>
                      
                      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs text-gray-500 mt-4 border-t border-gray-50 pt-3">
                         {row.Prefecture && (
                           <>
                             <dt className="text-gray-400">撮影地</dt>
                             <dd className="font-medium text-gray-700 text-right truncate">{row.Prefecture}</dd>
                           </>
                         )}
                         {row.Camera && (
                           <>
                             <dt className="text-gray-400">カメラ</dt>
                             <dd className="font-medium text-gray-700 text-right truncate">{row.Camera}</dd>
                           </>
                         )}
                      </dl>
                    </div>
                  </motion.div>
                );
              })}
            </div>

            {/* ページネーション */}
            {totalPages > 1 && (
              <div className="flex justify-center items-center mt-12 gap-2">
                <button
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage === 1}
                  className="p-2 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-5 h-5" />
                </button>
                
                <div className="flex gap-1">
                  {Array.from({ length: totalPages }, (_, i) => i + 1)
                    .filter(p => p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1)
                    .map((p, i, arr) => {
                      if (i > 0 && arr[i] - arr[i - 1] > 1) {
                        return <span key={`ellipsis-${p}`} className="px-2 py-1 text-gray-400">...</span>;
                      }
                      return (
                        <button
                          key={p}
                          onClick={() => handlePageChange(p)}
                          className={`w-10 h-10 rounded-full flex items-center justify-center font-medium transition-colors ${
                            currentPage === p 
                              ? 'bg-gray-900 text-white' 
                              : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                          }`}
                        >
                          {p}
                        </button>
                      );
                    })}
                </div>

                <button
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage === totalPages}
                  className="p-2 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-5 h-5" />
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* 画像拡大モーダル */}
      {selectedImage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4 md:p-8" onClick={() => setSelectedImage(null)}>
          <button 
            className="absolute top-4 right-4 md:top-8 md:right-8 text-white/70 hover:text-white p-2 rounded-full bg-black/20 hover:bg-black/40 transition-colors"
            onClick={() => setSelectedImage(null)}
          >
            <X className="w-8 h-8" />
          </button>
          <div className="relative max-w-full max-h-full flex flex-col items-center">
            <img 
              src={selectedImage} 
              alt="Expanded view" 
              className="max-w-full max-h-[85vh] object-contain select-none shadow-2xl"
              onClick={(e) => e.stopPropagation()}
              referrerPolicy="no-referrer"
              onError={(e) => {
                const target = e.target as HTMLImageElement;
                target.style.display = 'none';
              }}
            />
            {/* Show link to original if it follows our structure (replace PicsDB4Search with PicsDB_FM_Original_Pics) */}
            {selectedImage.includes('PicsDB4Search') && (
              <a 
                href={selectedImage.replace('PicsDB4Search', 'PicsDB_FM_Original_Pics')} 
                target="_blank" 
                rel="noreferrer"
                className="mt-4 text-white/80 hover:text-white text-sm font-medium border border-white/30 px-4 py-2 rounded-full hover:bg-white/10 transition-colors"
                onClick={(e) => e.stopPropagation()}
              >
                高画質オリジナル画像を別タブで開く
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ContestDatabasePage;
