import React, { useState, useEffect } from "react";
import { collection, query, getDocs, addDoc, deleteDoc, doc, updateDoc } from "firebase/firestore";
import { db } from "../firebase";
import { Plus, Edit, Trash2, X, Check } from "lucide-react";

interface SeasonalArchiveNews {
  id: string;
  category: string;
  dateStr: string;
  headline: string;
  url: string;
  location: string;
  date: string;
}

export default function AdminSeasonalNews() {
  const [newsList, setNewsList] = useState<SeasonalArchiveNews[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  
  // Form state
  const [form, setForm] = useState<Partial<SeasonalArchiveNews>>({});

  useEffect(() => {
    fetchNews();
  }, []);

  const fetchNews = async () => {
    setIsLoading(true);
    try {
      const q = query(collection(db, "archive"));
      const snaps = await getDocs(q);
      const fetched: SeasonalArchiveNews[] = [];
      snaps.forEach(d => {
        fetched.push({ id: d.id, ...d.data() } as SeasonalArchiveNews);
      });
      // Sort in JS for simplicity since we might not have a composite index
      fetched.sort((a, b) => b.dateStr.localeCompare(a.dateStr));
      setNewsList(fetched);
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateNew = () => {
    setEditingId('new');
    setForm({
      headline: '',
      url: '',
      location: '',
      date: '',
      category: '自然',
      dateStr: new Date().toISOString().split('T')[0]
    });
  };

  const handleEdit = (n: SeasonalArchiveNews) => {
    setEditingId(n.id);
    setForm(n);
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("本当に削除しますか？")) return;
    try {
      await deleteDoc(doc(db, "archive", id));
      setNewsList(prev => prev.filter(n => n.id !== id));
    } catch (err) {
      console.error(err);
      alert("削除に失敗しました");
    }
  };

  const handleSave = async () => {
    try {
      if (editingId === 'new') {
        const docRef = await addDoc(collection(db, "archive"), form);
        setNewsList([{ id: docRef.id, ...form } as SeasonalArchiveNews, ...newsList].sort((a, b) => b.dateStr.localeCompare(a.dateStr)));
      } else if (editingId) {
        await updateDoc(doc(db, "archive", editingId), form);
        setNewsList(prev => prev.map(n => n.id === editingId ? { ...n, ...form } as SeasonalArchiveNews : n).sort((a, b) => b.dateStr.localeCompare(a.dateStr)));
      }
      setEditingId(null);
      setForm({});
    } catch (err) {
      console.error(err);
      alert("保存に失敗しました");
    }
  };

  return (
    <div className="bg-white p-8 md:p-12 rounded-sm shadow-sm border border-stone-200">
      <div className="flex justify-between items-center mb-8">
        <h2 className="text-3xl font-serif text-emerald-950">旬撮ニュース管理</h2>
        <button 
          onClick={handleCreateNew}
          className="bg-emerald-700 text-white px-4 py-2 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-600 transition-colors"
        >
          <Plus className="w-4 h-4" /> 新規追加
        </button>
      </div>

      {editingId && (
        <div className="bg-stone-50 p-6 rounded-sm border border-stone-200 mb-8 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-stone-500 mb-1">ニュース見出し <span className="text-red-500">*</span></label>
              <input type="text" value={form.headline || ''} onChange={e => setForm({...form, headline: e.target.value})} className="w-full p-2 border border-stone-300 rounded-sm" />
            </div>
            <div>
              <label className="block text-xs font-bold text-stone-500 mb-1">URL <span className="text-red-500">*</span></label>
              <input type="text" value={form.url || ''} onChange={e => setForm({...form, url: e.target.value})} className="w-full p-2 border border-stone-300 rounded-sm" />
            </div>
            <div>
              <label className="block text-xs font-bold text-stone-500 mb-1">地域 (例: 北海道)</label>
              <input type="text" value={form.location || ''} onChange={e => setForm({...form, location: e.target.value})} className="w-full p-2 border border-stone-300 rounded-sm" />
            </div>
            <div>
              <label className="block text-xs font-bold text-stone-500 mb-1">表示用日付 (例: 4月30日)</label>
              <input type="text" value={form.date || ''} onChange={e => setForm({...form, date: e.target.value})} className="w-full p-2 border border-stone-300 rounded-sm" />
            </div>
            <div>
              <label className="block text-xs font-bold text-stone-500 mb-1">カテゴリー</label>
              <select value={form.category || '自然'} onChange={e => setForm({...form, category: e.target.value})} className="w-full p-2 border border-stone-300 rounded-sm bg-white">
                <option value="自然">自然</option>
                <option value="気象">気象</option>
                <option value="行事">行事</option>
                <option value="交通">交通</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold text-stone-500 mb-1">ソート用日付 (YYYY-MM-DD) <span className="text-red-500">*</span></label>
              <input type="date" value={form.dateStr || ''} onChange={e => setForm({...form, dateStr: e.target.value})} className="w-full p-2 border border-stone-300 rounded-sm" />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-4">
             <button onClick={() => setEditingId(null)} className="px-4 py-2 border border-stone-300 rounded-sm text-stone-600 font-bold hover:bg-stone-100 flex items-center gap-1"><X className="w-4 h-4"/> キャンセル</button>
             <button onClick={handleSave} className="px-4 py-2 bg-emerald-700 text-white rounded-sm font-bold hover:bg-emerald-600 flex items-center gap-1"><Check className="w-4 h-4"/> 保存</button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-8 text-stone-500">読み込み中...</div>
      ) : (
        <div className="bg-white border border-stone-200 rounded-sm overflow-hidden">
          <table className="w-full text-left">
            <thead className="bg-stone-100 border-b border-stone-200 uppercase text-[10px] font-bold tracking-widest text-emerald-800">
              <tr>
                <th className="px-4 py-3">日付</th>
                <th className="px-4 py-3">カテゴリー</th>
                <th className="px-4 py-3">見出し</th>
                <th className="px-4 py-3">アクション</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {newsList.map(n => (
                <tr key={n.id} className="hover:bg-stone-50 transition-colors">
                  <td className="px-4 py-3 text-xs font-mono">{n.dateStr}</td>
                  <td className="px-4 py-3"><span className="px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded-full text-xs font-bold">{n.category}</span></td>
                  <td className="px-4 py-3 font-medium text-sm">{n.headline}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                       <button onClick={() => handleEdit(n)} className="p-1.5 text-stone-400 hover:text-emerald-600"><Edit className="w-4 h-4"/></button>
                       <button onClick={() => handleDelete(n.id)} className="p-1.5 text-stone-400 hover:text-red-600"><Trash2 className="w-4 h-4"/></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
