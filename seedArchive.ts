import { initializeApp } from 'firebase/app';
import { getFirestore, collection, addDoc, getDocs, writeBatch } from 'firebase/firestore';
import firebaseConfig from './firebase-applet-config.json';

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);

const pastNews = [
  // 2026
  { headline: "気象庁：北海道大雪山系で初冠雪", url: "#", location: "北海道", date: "9月25日", category: "気象", dateStr: "2026-09-25" },
  { headline: "国営ひたち海浜公園：コキアの紅葉が見頃", url: "#", location: "茨城", date: "10月15日", category: "自然", dateStr: "2026-10-15" },
  { headline: "京都・嵐山：花灯路ライトアップ開始", url: "#", location: "京都", date: "12月10日", category: "行事", dateStr: "2026-12-10" },
  { headline: "知床：流氷接岸初日を観測", url: "#", location: "北海道・知床", date: "2月2日", category: "自然", dateStr: "2026-02-02" },
  { headline: "河津桜まつり：満開宣言", url: "#", location: "静岡", date: "2月20日", category: "自然", dateStr: "2026-02-20" },
  { headline: "弘前公園さくらまつり：開幕", url: "#", location: "青森", date: "4月20日", category: "行事", dateStr: "2026-04-20" },

  // 2025
  { headline: "志賀草津高原ルート雪の回廊開通", url: "#", location: "群馬/長野", date: "4月24日", category: "交通", dateStr: "2025-04-24" },
  { headline: "富山・立山：雪の大谷ウォーク", url: "#", location: "富山", date: "4月15日", category: "行事", dateStr: "2025-04-15" },
  { headline: "三陸復興国立公園：海霧の発生ピーク", url: "#", location: "岩手", date: "6月10日", category: "気象", dateStr: "2025-06-10" },
  { headline: "白川郷：ライトアップイベント", url: "#", location: "岐阜", date: "1月15日", category: "行事", dateStr: "2025-01-15" },
  { headline: "青森・奥入瀬渓流：新緑が見頃", url: "#", location: "青森", date: "5月20日", category: "自然", dateStr: "2025-05-20" },
  { headline: "ビーナスライン：全線開通", url: "#", location: "長野", date: "4月25日", category: "交通", dateStr: "2025-04-25" },
  { headline: "富士山：初冠雪を観測", url: "#", location: "山梨/静岡", date: "10月2日", category: "気象", dateStr: "2025-10-02" },

  // 2024
  { headline: "長岡まつり大花火大会：開催", url: "#", location: "新潟", date: "8月2日", category: "行事", dateStr: "2024-08-02" },
  { headline: "磐梯吾妻スカイライン：紅葉見頃", url: "#", location: "福島", date: "10月10日", category: "自然", dateStr: "2024-10-10" },
  { headline: "美瑛・白金青い池：ライトアップ開始", url: "#", location: "北海道", date: "11月1日", category: "行事", dateStr: "2024-11-01" },
  { headline: "ダイヤモンド筑波観測の好条件", url: "#", location: "茨城", date: "2月15日", category: "気象", dateStr: "2024-02-15" },
  { headline: "袋田の滝：氷瀑（完全凍結）を確認", url: "#", location: "茨城", date: "1月25日", category: "自然", dateStr: "2024-01-25" },
  { headline: "吉野山：シロヤマザクラ満開", url: "#", location: "奈良", date: "4月10日", category: "自然", dateStr: "2024-04-10" },
  
  // 2023
  { headline: "石垣島：サガリバナの見頃", url: "#", location: "沖縄", date: "6月25日", category: "自然", dateStr: "2023-06-25" },
  { headline: "黒部峡谷トロッコ電車：全線運行開始", url: "#", location: "富山", date: "5月5日", category: "交通", dateStr: "2023-05-05" },
  { headline: "高知・四万十川：沈下橋周辺のホタル飛交", url: "#", location: "高知", date: "5月30日", category: "自然", dateStr: "2023-05-30" },
  { headline: "宮島：水中花火大会（過去振り返り）", url: "#", location: "広島", date: "8月11日", category: "行事", dateStr: "2023-08-11" },
];

async function seed() {
  const archiveCol = collection(db, "archive");
  const existing = await getDocs(archiveCol);
  console.log("Existing archive items:", existing.size);
  
  // if (existing.size > 0) return; // We allow adding if they want

  const batch = writeBatch(db);
  for (const news of pastNews) {
    const docRef = addDoc(archiveCol, news); // Wait, addDoc creates new reference. Better use batch.
  }
  
  for(const news of pastNews) {
    await addDoc(archiveCol, news);
  }
  console.log("Seeded archives");
}

seed().catch(console.error);
