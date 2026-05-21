import React, { useState } from 'react';
import Papa from 'papaparse';
import { collection, writeBatch, doc } from 'firebase/firestore';
import { db } from '../firebase';
import { Database, AlertCircle, CheckCircle } from 'lucide-react';

const ImportFirebasePage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState({ current: 0, total: 0 });

  const handleImport = async () => {
    setLoading(true);
    setMessage(null);
    setError(null);
    setProgress({ current: 0, total: 0 });

    try {
      // 1. Fetch the CSV
      const response = await fetch('/sample_database.csv');
      if (!response.ok) {
        throw new Error(`CSVの取得に失敗しました: ${response.statusText}`);
      }
      
      const csvText = await response.text();
      
      // 2. Parse the CSV
      Papa.parse(csvText, {
        header: true,
        skipEmptyLines: true,
        complete: async (results) => {
          if (results.errors.length > 0) {
            console.warn('CSV Parse Warnings:', results.errors);
          }

          const data = results.data as any[];
          if (data.length === 0) {
            setError("CSVファイルにデータがありません。");
            setLoading(false);
            return;
          }

          setProgress({ current: 0, total: data.length });
          
          // 3. Batch write to Firestore (max 500 per batch)
          try {
            const BATCH_SIZE = 400; // Safe margin below 500
            let currentBatch = writeBatch(db);
            let operationCount = 0;
            
            const commitWithTimeout = async (batch: any) => {
              return new Promise((resolve, reject) => {
                const timer = setTimeout(() => {
                  reject(new Error("Firestoreとの通信がタイムアウトしました。環境設定（Firebase Config）が「AIzaSy...」のような仮の値になっていないか、あるいはデータベースのルール設定を確認してください。"));
                }, 10000); // 10秒でタイムアウト

                batch.commit().then(() => {
                  clearTimeout(timer);
                  resolve(true);
                }).catch((err: any) => {
                  clearTimeout(timer);
                  reject(err);
                });
              });
            };
            
            for (let i = 0; i < data.length; i++) {
              const row = data[i];
              // doc reference (auto-generated ID)
              const docRef = doc(collection(db, "contests"));
              currentBatch.set(docRef, row);
              
              operationCount++;
              
              // Commit if batch is full or it's the last item
              if (operationCount >= BATCH_SIZE || i === data.length - 1) {
                await commitWithTimeout(currentBatch);
                currentBatch = writeBatch(db); // new batch
                operationCount = 0;
                setProgress({ current: i + 1, total: data.length });
              }
            }
            
            setMessage(`${data.length}件のデータをFirestoreへインポートしました。`);
          } catch (err: any) {
            setError(`Firestoreへの書き込みエラー: ${err.message}`);
          } finally {
            setLoading(false);
          }
        },
        error: (err: any) => {
          setError(`CSVの解析に失敗しました: ${err.message}`);
          setLoading(false);
        }
      });
    } catch (err: any) {
      setError(`エラーが発生しました: ${err.message}`);
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-stone-50 py-12 px-4 sm:px-6 lg:px-8 font-sans">
      <div className="max-w-xl mx-auto bg-white rounded-lg shadow p-8">
        <h1 className="text-2xl font-bold text-stone-800 mb-6 flex items-center gap-2">
          <Database className="w-6 h-6 text-emerald-600" />
          Firestore インポートツール
        </h1>
        
        <p className="text-stone-600 mb-8 leading-relaxed">
          公開用CSVファイル（<code className="bg-stone-100 px-1 py-0.5 rounded">/sample_database.csv</code>）のデータを読み込み、Firestoreの「contests」コレクションに一括登録します。この操作は既存のデータを上書きするものではなく、新しく追加されます。
        </p>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-red-700">{error}</div>
          </div>
        )}

        {message && (
          <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 rounded-lg flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-emerald-500 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-emerald-700 font-medium">{message}</div>
          </div>
        )}

        {loading && progress.total > 0 && (
          <div className="mb-8">
            <div className="flex justify-between text-sm text-stone-600 mb-2">
              <span>インポート中...</span>
              <span>{progress.current} / {progress.total}</span>
            </div>
            <div className="w-full bg-stone-200 rounded-full h-2.5">
              <div 
                className="bg-emerald-600 h-2.5 rounded-full transition-all duration-300"
                style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
              ></div>
            </div>
          </div>
        )}

        <button
          onClick={handleImport}
          disabled={loading}
          className="w-full py-3 px-4 bg-emerald-700 hover:bg-emerald-800 text-white font-medium rounded-lg shadow transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center gap-2"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              処理中...
            </>
          ) : (
            'データをインポートする'
          )}
        </button>
      </div>
    </div>
  );
};

export default ImportFirebasePage;
